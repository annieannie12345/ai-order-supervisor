import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201b",
        panel: "#fbfcfb",
        line: "#d8ded9",
        moss: "#486f5b",
        mint: "#dcece3",
        amber: "#b9812f",
        coral: "#c65d4a"
      },
      boxShadow: {
        soft: "0 10px 30px rgba(23, 32, 27, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
