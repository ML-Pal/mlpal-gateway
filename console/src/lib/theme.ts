/** Dark mode: system preference by default, explicit choice persisted. The
 * MLPal tokens flip on the `.dark` class on <html>. */

const KEY = "mlpal.console.theme";

export type Theme = "light" | "dark";

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function currentTheme(): Theme {
  const stored = localStorage.getItem(KEY);
  if (stored === "light" || stored === "dark") return stored;
  return systemTheme();
}

function apply(theme: Theme) {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

/** Call once at boot: applies stored/system theme and follows OS changes while
 * the user hasn't made an explicit choice. */
export function initTheme(): void {
  apply(currentTheme());
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (!localStorage.getItem(KEY)) apply(systemTheme());
  });
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  localStorage.setItem(KEY, next);
  apply(next);
  return next;
}
