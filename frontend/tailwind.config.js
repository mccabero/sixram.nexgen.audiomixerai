/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(148, 163, 184, 0.14), 0 24px 80px rgba(0, 0, 0, 0.42)",
      },
    },
  },
  plugins: [],
};

