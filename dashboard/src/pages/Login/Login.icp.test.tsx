import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: () => Promise.resolve({ setup_required: false }),
    getOauthStatus: () => Promise.resolve({ providers: [] }),
    getLdapStatus: () => Promise.resolve({ enabled: false }),
    getCaptcha: () => Promise.resolve({ provider: "none" }),
  },
}));

vi.mock("../../utils/locale", () => ({
  applyGuestLocale: () => Promise.resolve(),
  applyUserLocale: () => Promise.resolve(),
}));

vi.mock("./CaptchaField", () => ({
  default: () => null,
}));

import LoginPage from "./index";
import {
  DEFAULT_ICP_FILING_NUMBER,
  ICP_FILING_URL,
} from "../../config/icpFiling";

describe("Login ICP filing footer", () => {
  it("shows filing number link to miit beian", () => {
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );

    const link = screen.getByTestId("icp-filing-link");
    expect(link).toHaveTextContent(DEFAULT_ICP_FILING_NUMBER);
    expect(link).toHaveAttribute("href", ICP_FILING_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });
});
