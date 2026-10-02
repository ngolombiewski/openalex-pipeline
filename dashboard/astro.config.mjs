// @ts-check
import { defineConfig } from "astro/config";

// GitHub Pages project site: every URL lives beneath the repository path.
export default defineConfig({
  site: "https://ngolombiewski.github.io",
  base: "/openalex-pipeline",
  output: "static",
});
