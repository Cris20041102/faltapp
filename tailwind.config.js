// Estilo inspirado en Wope (violeta, vidrio, botones píldora) con modo claro y oscuro.
// Cada color es una variable CSS con un valor por modo: las clases de la app (slate-500, indigo-600…) sirven para ambos.
// Modo: el del dispositivo (prefers-color-scheme) o el elegido en Perfil (<html data-theme="light|dark">).
const T = { // paletas de Tailwind 3: 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950
  green: ["#f0fdf4", "#dcfce7", "#bbf7d0", "#86efac", "#4ade80", "#22c55e", "#16a34a", "#15803d", "#166534", "#14532d", "#052e16"],
  red: ["#fef2f2", "#fee2e2", "#fecaca", "#fca5a5", "#f87171", "#ef4444", "#dc2626", "#b91c1c", "#991b1b", "#7f1d1d", "#450a0a"],
  amber: ["#fffbeb", "#fef3c7", "#fde68a", "#fcd34d", "#fbbf24", "#f59e0b", "#d97706", "#b45309", "#92400e", "#78350f", "#451a03"],
  yellow: ["#fefce8", "#fef9c3", "#fef08a", "#fde047", "#facc15", "#eab308", "#ca8a04", "#a16207", "#854d0e", "#713f12", "#422006"],
  sky: ["#f0f9ff", "#e0f2fe", "#bae6fd", "#7dd3fc", "#38bdf8", "#0ea5e9", "#0284c7", "#0369a1", "#075985", "#0c4a6e", "#082f49"],
};
const KEYS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
// modo oscuro "invertido": fondos claros (50–300) pasan a oscuros, textos oscuros (700–900) a claros, rellenos (400–600) igual
const invert = (c) => [10, 9, 8, 7, 4, 5, 6, 3, 2, 1, 0].map((i) => c[i]);
const PALETTES = { // [claro, oscuro]
  ...Object.fromEntries(Object.entries(T).map(([n, c]) => [n, [c, invert(c)]])),
  // grises con tinte lila (Ash Lilac, Muted Steel, Dim Fog)
  slate: [["#f8f7fc", "#f1eff7", "#e6e3ef", "#d2d0dd", "#9b96b0", "#6b6680", "#57536a", "#3d3950", "#24202f", "#0c0616", "#0c0616"],
          ["#120a24", "#1a1030", "#2a2140", "#3b3354", "#85808c", "#9b96b0", "#b5b1c6", "#d2d0dd", "#e9e8ef", "#ffffff", "#ffffff"]],
  // el acento (antes índigo) es el violeta de Wope, #713dff en el 500
  indigo: [["#f4f0ff", "#ebe4ff", "#d9ccff", "#bba5ff", "#9474ff", "#713dff", "#5b2be0", "#4c1fc4", "#3f1a9e", "#33177d", "#1f0d4d"],
           ["#150b2c", "#1f1145", "#2e1a66", "#4b2fa0", "#9d82ff", "#713dff", "#8562ff", "#b7a4fb", "#d4c9fd", "#ece7fe", "#f6f3ff"]],
};
const SEMANTIC = { // [claro, oscuro]
  fg: ["12 6 22", "255 255 255"], // texto principal
  canvas: ["246 244 251", "10 1 24"], // fondo (Night Violet en oscuro)
  surface: ["rgb(255 255 255 / .75)", "rgb(255 255 255 / .04)"], // vidrio de tarjetas
  sheet: ["#ffffff", "#120a24"], // diálogos
  scheme: ["light", "dark"], // calendarios y selects nativos
  g1: [".16", ".5"], g2: [".22", ".28"], g3: [".1", ".16"], // intensidad del brillo violeta
};
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(" ");
const vars = (m) => ({
  ...Object.fromEntries(Object.entries(PALETTES).flatMap(([n, p]) => KEYS.map((k, i) => [`--${n}-${k}`, rgb(p[m][i])]))),
  ...Object.fromEntries(Object.entries(SEMANTIC).map(([k, v]) => [`--${k}`, v[m]])),
});
const channel = (v) => `rgb(var(--${v}) / <alpha-value>)`;

module.exports = {
  content: { relative: true, files: ["./static/*.{html,js}"] },
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(Object.keys(PALETTES).map((n) => [n, Object.fromEntries(KEYS.map((k) => [k, channel(`${n}-${k}`)]))])),
        fg: channel("fg"), canvas: channel("canvas"), surface: "var(--surface)", sheet: "var(--sheet)",
        night: "#0a0118", // texto oscuro fijo sobre rellenos claros (amarillo del semáforo)
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        display: ["Sora", "Inter", "ui-sans-serif", "system-ui", "sans-serif"], // solo títulos y logo
      },
      borderRadius: { xl: "10px", "2xl": "16px" }, // filas 10px, tarjetas 16px; botones = píldora
    },
  },
  plugins: [({ addBase }) => addBase({
    ":root": vars(0),
    "@media (prefers-color-scheme: dark)": { ":root:not([data-theme=light])": vars(1) },
    ":root[data-theme=dark]": vars(1),
  })],
};
