#!/usr/bin/env bash
# Claude Code Stop hook: mirror each turn (user prompt + final assistant
# response) onto a per-session GitHub thread — a Discussion in the "Show and
# tell" category when the repo has Discussions enabled, or an Issue otherwise
# — created on the first turn, commented on subsequent turns. The title is
# Claude Code's own auto-generated session title (the transcript's ai-title)
# plus a "[<session UUID>]" suffix.
# The suffix is the stable lookup key; the human half tracks ai-title (see
# the note above the title refreshers for how manual renames interact).
#
# This is a logging side-effect, so it must never interrupt the conversation:
# every failure path emits {"systemMessage": ...} (visible in the Claude Code
# UI) and exits 0.
#
# Set TURN_LOG_DRY_RUN=1 to print the would-be title/body to stderr instead
# of calling GitHub. Set TURN_LOG_DISABLE=1 (e.g. in your shell profile) to
# keep your sessions out of the issue log entirely.

set -o pipefail

[ "${TURN_LOG_DISABLE:-0}" = "1" ] && exit 0

say() {
  if command -v jq >/dev/null 2>&1; then
    jq -cn --arg m "[gh-turn-log] $1" '{systemMessage: $m}'
  else
    printf '{"systemMessage":"[gh-turn-log] %s"}\n' "$1"
  fi
  exit 0
}

command -v jq >/dev/null 2>&1 || say "jq is not installed - turn NOT logged to GitHub (brew install jq)"
command -v gh >/dev/null 2>&1 || say "GitHub CLI (gh) is not installed - turn NOT logged to GitHub (brew install gh)"

INPUT=$(cat)
SESSION_ID=$(jq -r '.session_id // empty' <<<"$INPUT" 2>/dev/null)
TRANSCRIPT=$(jq -r '.transcript_path // empty' <<<"$INPUT" 2>/dev/null)
CWD=$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)

[[ "$SESSION_ID" =~ ^[0-9a-fA-F-]+$ ]] || say "missing or unexpected session_id in hook input"
[ -f "$TRANSCRIPT" ] || say "transcript not found: $TRANSCRIPT"
[ -d "$CWD" ] && cd "$CWD"

# Last real user prompt: skip sidechains, meta entries (skill/command
# injections), and tool results; join text blocks, dropping system-reminders.
# Reading the transcript is safe on the prompt side: the prompt line is
# written at submit time, long before Stop fires.
USER_PROMPT=$(jq -rs '
  [ .[]
    | select(.type == "user" and .isMeta != true and .isSidechain != true)
    | select(has("toolUseResult") | not)
    | .message.content
    | if type == "string" then .
      elif type == "array" then
        if any(.[]?; .type == "tool_result") then empty
        else ([.[] | select(.type == "text") | .text
               | select(startswith("<system-reminder>") | not)]
              | join("\n"))
        end
      else empty
      end
    | select(length > 0)
    | select(test("^<(command|local-command)") | not)
  ] | last // empty
' "$TRANSCRIPT") || say "failed to parse transcript for user prompt"

# Final assistant response: taken from the Stop payload itself, NOT the
# transcript. The transcript is written asynchronously and lags the turn, so
# reading it here races and can capture an earlier interim message; the docs
# say to use last_assistant_message on Stop for the current turn's text. If
# the field is absent or empty (tool-calls-only turn), the placeholder below
# is used — deliberately never the transcript, which would post stale text.
# Shape-tolerant: current builds (verified in v2.1.206) pass a plain string
# of the joined text blocks; accept an object ({text} or API-style {content})
# too in case the payload shape changes.
ASSISTANT_TEXT=$(jq -r '
  .last_assistant_message // empty
  | if type == "string" then .
    else (.text // ([.content[]? | select(.type == "text") | .text] | join("\n")))
    end
' <<<"$INPUT" 2>/dev/null)

[ -n "$USER_PROMPT" ] || say "no user prompt found in transcript - nothing logged"
[ -n "$ASSISTANT_TEXT" ] || ASSISTANT_TEXT="_(no final text response this turn)_"

# GitHub's HTML sanitizer strips unknown tags (e.g. <discovery>) from the
# RENDERED view (the raw body keeps them), so XML-ish tags in the quoted
# prompt silently vanish on the page. Entity-escape & and < in the prompt —
# but only outside fenced code blocks and inline `code` spans, where GitHub
# already renders them literally and an entity would display as-is. This is
# display-only fidelity, not a security measure: GitHub sanitizes server-side
# regardless, and escaping makes text more inert, never less. Known limit:
# multi-backtick spans (``like this``) confuse the per-line span split. The
# response half is left untouched — it is markdown authored for rendering.
ESCAPED_PROMPT=$(printf '%s\n' "$USER_PROMPT" | awk '
  /^[[:space:]]*(```|~~~)/ { fence = !fence; print; next }
  fence { print; next }
  {
    n = split($0, seg, /`/)
    out = ""
    for (i = 1; i <= n; i++) {
      s = seg[i]
      if (i % 2 == 1) { gsub(/&/, "\\&amp;", s); gsub(/</, "\\&lt;", s) }
      out = out s (i < n ? "`" : "")
    }
    print out
  }
')
BODY=$(printf '%s\n' "$ESCAPED_PROMPT" | sed 's/^/> /'; printf '\n%s\n' "$ASSISTANT_TEXT")

# GitHub caps issue/comment bodies at 65536 chars.
if [ "${#BODY}" -gt 60000 ]; then
  BODY="${BODY:0:60000}

_[truncated]_"
fi

# Footer: model ID and effort level. The Stop payload carries effort (an
# object {level: "..."} in current builds — accept a plain string too) but no
# model field, so the model ID comes from the transcript's last real
# assistant message ("<synthetic>" entries excluded); after a mid-session
# model switch it can lag one turn, which is fine for attribution. Appended
# after the truncation cap so the footer itself is never cut. Omitted
# entirely when neither value is available.
MODEL=$(jq -rs '[.[] | select(.type == "assistant") | .message.model
  | select(. != null and . != "<synthetic>")] | last // empty' "$TRANSCRIPT" 2>/dev/null)
EFFORT=$(jq -r '.effort | (if type == "object" then .level else . end) // empty' <<<"$INPUT" 2>/dev/null)
FOOTER="$MODEL"
[ -n "$EFFORT" ] && FOOTER="${FOOTER:+$FOOTER · }effort: $EFFORT"
if [ -n "$FOOTER" ]; then
  BODY="$BODY

---
<em>$FOOTER</em>"
fi

# Issue title: Claude Code's auto-generated session title — the transcript's
# ai-title entries — with the session UUID as a bracketed suffix so the lookup
# below stays deterministic no matter how the human half reads. ai-title is
# written asynchronously and may be missing on early Stops; fall back to the
# bare "[UUID]" and let the refresh below rename the issue once it lands.
# Sanitize and cap inside jq: its slicing is per codepoint, unlike cut -c,
# which counts bytes and can split a multi-byte UTF-8 character.
AI_TITLE=$(jq -rs 'map(select(.type == "ai-title"))[-1].aiTitle // ""
  | gsub("[\r\n\t]+"; " ") | sub("^ +"; "") | sub(" +$"; "") | .[0:160]' "$TRANSCRIPT" 2>/dev/null)
if [ -n "$AI_TITLE" ]; then
  TITLE="$AI_TITLE [$SESSION_ID]"
else
  TITLE="[$SESSION_ID]"
fi

# Session state file: line 1 caches the posting target — a GraphQL node id
# ("D_...") for a discussion, a plain number for an issue — so later turns
# post directly with no lookup; line 2 holds the checksum of the last posted
# body (Stop also fires on resume/clear/compact; identical reposts are
# skipped); line 3 holds the title we last set (so the title refresh only
# fires when the composed title actually changed).
STATE="${TMPDIR:-/tmp}/gh-turn-log-${SESSION_ID}.state"
SUM=$(printf '%s' "$BODY" | cksum | awk '{print $1}')
CACHED_TARGET=$(sed -n 1p "$STATE" 2>/dev/null)
LAST_TITLE=$(sed -n 3p "$STATE" 2>/dev/null)
[ "$(sed -n 2p "$STATE" 2>/dev/null)" = "$SUM" ] && exit 0

if [ "${TURN_LOG_DRY_RUN:-0}" = "1" ]; then
  printf 'DRY RUN - issue title: %s\n----- body -----\n%s\n' "$TITLE" "$BODY" >&2
  exit 0
fi

ERRF=$(mktemp "${TMPDIR:-/tmp}/gh-turn-log-err.XXXXXX") || say "mktemp failed"
trap 'rm -f "$ERRF"' EXIT

save_state() { printf '%s\n%s\n%s\n' "$1" "$SUM" "$LAST_TITLE" >"$STATE"; }

# Title refreshes are cosmetic and best-effort: they no-op when the composed
# title matches the one the hook LAST SET (state line 3 — the live GitHub
# title is never read on the fast path), and a failed rename never aborts
# the turn's log (it retries next turn). Consequently a manual rename on
# GitHub persists until the composed title next changes, or until a
# cold-path lookup — which seeds LAST_TITLE from the live title and so
# re-asserts the hook's version. Manual renames must keep the "[<uuid>]"
# suffix, or the cold-path lookup can't find the thread and a cache loss
# would spawn a duplicate.
refresh_issue_title() {  # $1 = issue number
  [ "$TITLE" = "$LAST_TITLE" ] && return 0
  gh issue edit "$1" --title "$TITLE" >/dev/null 2>&1
}
refresh_discussion_title() {  # $1 = discussion node id
  [ "$TITLE" = "$LAST_TITLE" ] && return 0
  gh api graphql -f query='mutation($id: ID!, $title: String!) {
    updateDiscussion(input: {discussionId: $id, title: $title}) { discussion { id } }
  }' -f id="$1" -f title="$TITLE" >/dev/null 2>&1
}

comment_discussion() {  # $1 = discussion node id
  gh api graphql -f query='mutation($id: ID!, $body: String!) {
    addDiscussionComment(input: {discussionId: $id, body: $body}) { comment { id } }
  }' -f id="$1" -f body="$BODY" >/dev/null 2>"$ERRF"
}

# Fast path: post to the cached target; its shape encodes the mode (GraphQL
# discussion node ids start with "D_", issue numbers are numeric). Falls
# through to a fresh lookup if the post fails (stale state, target deleted).
if [[ "$CACHED_TARGET" == D_* ]]; then
  if comment_discussion "$CACHED_TARGET"; then
    refresh_discussion_title "$CACHED_TARGET" && LAST_TITLE="$TITLE"
    save_state "$CACHED_TARGET"
    exit 0
  fi
elif [[ "$CACHED_TARGET" =~ ^[0-9]+$ ]]; then
  if gh issue comment "$CACHED_TARGET" --body "$BODY" >/dev/null 2>"$ERRF"; then
    refresh_issue_title "$CACHED_TARGET" && LAST_TITLE="$TITLE"
    save_state "$CACHED_TARGET"
    exit 0
  fi
fi

# Cold path (at most once per session): pick the mode. Discussions are
# preferred when the repo has them enabled AND a "Show and tell" category
# exists; otherwise fall back to Issues.
REPO_META=$(gh api 'repos/{owner}/{repo}' 2>"$ERRF") \
  || say "gh repo lookup failed (not authed? no GitHub remote?): $(head -c 200 "$ERRF")"

if [ "$(jq -r '.has_discussions // false' <<<"$REPO_META")" = "true" ]; then
  # One query: the categories (to find "Show and tell") plus the 100 most
  # recently active discussions for the client-side title match — GitHub
  # search lags writes and tokenizes titles, same reason the issue path
  # avoids gh --search.
  DISC_META=$(gh api graphql -f query='query($owner: String!, $name: String!) {
    repository(owner: $owner, name: $name) {
      discussionCategories(first: 25) { nodes { id name } }
      discussions(first: 100, orderBy: {field: UPDATED_AT, direction: DESC}) {
        nodes { id title }
      }
    }
  }' -f owner="$(jq -r '.owner.login' <<<"$REPO_META")" \
     -f name="$(jq -r '.name' <<<"$REPO_META")" 2>"$ERRF") \
    || say "discussion lookup failed: $(head -c 200 "$ERRF")"

  CAT_ID=$(jq -r '[.data.repository.discussionCategories.nodes[]
    | select(.name | ascii_downcase == "show and tell")] | first | .id // empty' <<<"$DISC_META")
fi

if [ -n "${CAT_ID:-}" ]; then
  DISC_ID=$(jq -r --arg t "$SESSION_ID" '[.data.repository.discussions.nodes[]
    | select(.title | endswith("[\($t)]"))] | first | .id // empty' <<<"$DISC_META")
  if [ -n "$DISC_ID" ]; then
    comment_discussion "$DISC_ID" \
      || say "discussion comment failed: $(head -c 200 "$ERRF")"
    LAST_TITLE=$(jq -r --arg t "$SESSION_ID" '[.data.repository.discussions.nodes[]
      | select(.title | endswith("[\($t)]"))] | first | .title // empty' <<<"$DISC_META")
    refresh_discussion_title "$DISC_ID" && LAST_TITLE="$TITLE"
  else
    DISC_ID=$(gh api graphql -f query='mutation($repoId: ID!, $catId: ID!, $title: String!, $body: String!) {
      createDiscussion(input: {repositoryId: $repoId, categoryId: $catId, title: $title, body: $body}) {
        discussion { id }
      }
    }' -f repoId="$(jq -r '.node_id' <<<"$REPO_META")" -f catId="$CAT_ID" \
       -f title="$TITLE" -f body="$BODY" \
       --jq '.data.createDiscussion.discussion.id' 2>"$ERRF") \
      || say "discussion create failed: $(head -c 200 "$ERRF")"
    LAST_TITLE="$TITLE"
  fi
  save_state "$DISC_ID"
  exit 0
fi

# Issue fallback: title match via client-side filter over the most recent
# 1000 issues. Every title this hook sets ends in "[<uuid>]", so the suffix
# is the invariant lookup key.
LIST=$(gh issue list --state all --limit 1000 --json number,title 2>"$ERRF") \
  || say "gh issue list failed (not authed? no GitHub remote?): $(head -c 200 "$ERRF")"

ISSUE=$(jq -r --arg t "$SESSION_ID" \
  '[.[] | select(.title | endswith("[\($t)]"))] | first | .number // empty' <<<"$LIST")

if [ -n "$ISSUE" ]; then
  gh issue comment "$ISSUE" --body "$BODY" >/dev/null 2>"$ERRF" \
    || say "gh issue comment failed: $(head -c 200 "$ERRF")"
  LAST_TITLE=$(jq -r --arg t "$SESSION_ID" \
    '[.[] | select(.title | endswith("[\($t)]"))] | first | .title // empty' <<<"$LIST")
  refresh_issue_title "$ISSUE" && LAST_TITLE="$TITLE"
else
  URL=$(gh issue create --title "$TITLE" --body "$BODY" 2>"$ERRF") \
    || say "gh issue create failed: $(head -c 200 "$ERRF")"
  ISSUE=${URL##*/}
  LAST_TITLE="$TITLE"
fi

save_state "$ISSUE"
exit 0
