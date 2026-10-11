import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  keyLogin: vi.fn(),
  login: vi.fn(),
  setToken: vi.fn(),
}));
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getAuthStatus: async () => ({ setup_required: false }),
    getOauthStatus: async () => ({ providers: [] }),
    getLdapStatus: async () => ({ enabled: false }),
    getCaptcha: async () => ({ provider: "slider" }),
    keyLogin: auth.keyLogin,
    login: auth.login,
  },
}));
vi.mock("../../api", () => ({
  setAuthToken: auth.setToken,
  clearAuthToken: vi.fn(),
  setRememberLoginPreference: vi.fn(),
}));
vi.mock("../../utils/locale", () => ({
  applyGuestLocale: async () => {},
  applyUserLocale: async () => {},
}));
vi.mock("../../i18n", () => ({ refreshServerLabels: vi.fn() }));
vi.mock("./CaptchaField", () => ({
  default: () => <div data-testid="password-captcha" />,
}));
import LoginPage from "./index";

describe("account key login", () => {
  it("uses the key endpoint without username, password or password captcha", async () => {
    auth.keyLogin.mockResolvedValue({
      access_token: "short-session",
      user: { locale: "zh" },
    });
    render(
      <MemoryRouter>
        <LoginPage />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText(/login.keyMode|密钥登录|Key login/));
    expect(screen.queryByTestId("password-captcha")).toBeNull();
    fireEvent.change(
      screen.getByLabelText(/login.accessKey|账号登录密钥|Account access key/),
      { target: { value: "oak_test_only" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /login.submit|登.*录|Sign in/ }),
    );
    await waitFor(() =>
      expect(auth.keyLogin).toHaveBeenCalledWith("oak_test_only"),
    );
    expect(auth.login).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(auth.setToken).toHaveBeenCalledWith("short-session", true),
    );
  });
});
