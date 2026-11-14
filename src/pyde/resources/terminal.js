// The terminal page: xterm.js on screen, wired to a shell that Python runs.
//
// Python exposes one object over the Qt web channel, `pty`. Its signals carry
// the shell's output and settings to this page; its slots take the user's
// keystrokes and the terminal's size back.

const THEMES = {
  light: {
    background: "#ffffff",
    foreground: "#1f2328",
    cursor: "#1f2328",
    cursorAccent: "#ffffff",
    selectionBackground: "#b6d6fd",
    black: "#000000",
    red: "#cd3131",
    green: "#107c10",
    yellow: "#949800",
    blue: "#0451a5",
    magenta: "#bc05bc",
    cyan: "#0598bc",
    white: "#555555",
    brightBlack: "#666666",
    brightRed: "#cd3131",
    brightGreen: "#14ce14",
    brightYellow: "#b5ba00",
    brightBlue: "#0451a5",
    brightMagenta: "#bc05bc",
    brightCyan: "#0598bc",
    brightWhite: "#a5a5a5",
  },
  dark: {
    background: "#1e1e1e",
    foreground: "#d4d4d4",
    cursor: "#d4d4d4",
    cursorAccent: "#1e1e1e",
    selectionBackground: "#264f78",
    black: "#000000",
    red: "#cd3131",
    green: "#0dbc79",
    yellow: "#e5e510",
    blue: "#2472c8",
    magenta: "#bc3fbc",
    cyan: "#11a8cd",
    white: "#e5e5e5",
    brightBlack: "#666666",
    brightRed: "#f14c4c",
    brightGreen: "#23d18b",
    brightYellow: "#f5f543",
    brightBlue: "#3b8eea",
    brightMagenta: "#d670d6",
    brightCyan: "#29b8db",
    brightWhite: "#e5e5e5",
  },
};

const terminal = new Terminal({
  fontFamily: 'Menlo, Monaco, "Cascadia Mono", Consolas, monospace',
  fontSize: 13,
  cursorBlink: true,
  scrollback: 10000,
});
const fit = new FitAddon.FitAddon();
terminal.loadAddon(fit);
terminal.open(document.getElementById("terminal"));

function setTheme(dark) {
  const theme = dark ? THEMES.dark : THEMES.light;
  terminal.options.theme = theme;
  document.body.style.background = theme.background;
}

new QWebChannel(qt.webChannelTransport, (channel) => {
  const pty = channel.objects.pty;

  // Acknowledging each piece once xterm.js has drawn it lets Python hold the
  // shell back when output arrives faster than it can be shown.
  pty.output.connect((text) => terminal.write(text, () => pty.ack(text.length)));
  pty.theme.connect(setTheme);
  pty.focus.connect(() => terminal.focus());

  terminal.onData((text) => pty.write(text));
  terminal.onResize(({ cols, rows }) => pty.resize(rows, cols));
  new ResizeObserver(() => fit.fit()).observe(document.body);

  fit.fit();
  pty.start(terminal.rows, terminal.cols);
});

window.addEventListener("focus", () => terminal.focus());
