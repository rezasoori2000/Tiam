/** @type {import('tailwindcss').Config} */

// Every colour resolves to a CSS variable defined once in src/index.css (":root" = Night Shift
// theme; a light theme only needs to override the same variables under [data-theme="light"]).
// color-mix keeps Tailwind's opacity modifiers (bg-accent/10 etc.) working on hex tokens.
const token = (name) => `color-mix(in srgb, var(--${name}) calc(<alpha-value> * 100%), transparent)`;
const scale = (shades) =>
  Object.fromEntries(
    [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950].map((s) => [s, token(shades(s))])
  );

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: token("bg"),
        panel: token("panel"),
        "panel-2": token("panel-2"),
        line: token("border"),
        fg: token("text"),
        muted: token("text-muted"),
        accent: token("accent"),
        critical: token("critical"),
        warning: token("warning"),
        success: token("success"),
        // Legacy palette names still used across the pages, mapped onto the tokens so no
        // component carries a raw colour: slate = the neutral UI ramp, red/amber/emerald =
        // critical/warning/success, apl-midnight/sunset = background/accent.
        slate: scale((s) =>
          s <= 300 ? "text" : s <= 500 ? "text-muted" : s <= 700 ? "border" : s === 800 ? "panel-2" : s === 900 ? "panel" : "bg"
        ),
        red: scale(() => "critical"),
        amber: scale(() => "warning"),
        emerald: scale(() => "success"),
        apl: { midnight: token("bg"), sunset: token("accent") },
      },
      borderRadius: {
        sm: "var(--radius)",
        DEFAULT: "var(--radius)",
        md: "var(--radius)",
        lg: "var(--radius)",
        xl: "var(--radius)",
        "2xl": "var(--radius)",
        "3xl": "var(--radius)",
      },
      fontSize: {
        // body 13px; text-xs (labels) stays 12px; KPI numbers use text-2xl (24px)
        sm: ["13px", "18px"],
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["Inter", "system-ui", "sans-serif"],
      },
      keyframes: {
        "alert-pulse": {
          "0%, 100%": { boxShadow: "0 0 0 0 color-mix(in srgb, var(--critical) 55%, transparent)" },
          "50%": { boxShadow: "0 0 0 6px transparent" },
        },
        "slide-in-right": {
          from: { transform: "translateX(110%)", opacity: "0" },
          to: { transform: "translateX(0)", opacity: "1" },
        },
      },
      animation: {
        "alert-pulse": "alert-pulse 1.6s ease-in-out infinite",
        "slide-in-right": "slide-in-right 200ms ease-out",
      },
    },
  },
  plugins: [],
}
