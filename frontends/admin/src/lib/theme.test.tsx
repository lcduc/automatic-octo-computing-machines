import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ThemeToggle } from "../components/layout/ThemeToggle";
import { I18nProvider } from "../i18n/I18nProvider";
import { resolveTheme, ThemeProvider } from "./theme";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("theme", () => {
  it("follows the system only when asked to", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  it("cycles light → dark → system, sets <html data-theme> and remembers the choice", () => {
    window.localStorage.setItem("admin.theme", "light");
    render(
      <ThemeProvider>
        <I18nProvider>
          <ThemeToggle />
        </I18nProvider>
      </ThemeProvider>,
    );
    expect(document.documentElement.dataset.theme).toBe("light");

    fireEvent.click(screen.getByRole("button"));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("admin.theme")).toBe("dark");

    fireEvent.click(screen.getByRole("button"));
    expect(window.localStorage.getItem("admin.theme")).toBe("system");
    // jsdom has no matchMedia, so "system" resolves to light.
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
