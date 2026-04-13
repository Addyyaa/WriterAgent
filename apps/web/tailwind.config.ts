import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./modules/**/*.{ts,tsx}",
    "./shared/**/*.{ts,tsx}",
    "./server/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: "var(--ink)",
        mist: "var(--mist)",
        surge: "var(--surge)",
        ember: "var(--ember)",
        ocean: "var(--ocean)",
        graphite: "var(--graphite)"
      },
      boxShadow: {
        panel: "0 18px 60px rgba(3, 15, 27, 0.18)"
      }
    }
  },
  plugins: []
};

export default config;
