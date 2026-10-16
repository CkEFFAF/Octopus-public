import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import IcpFilingFooter from "./index";
import {
  DEFAULT_ICP_FILING_NUMBER,
  ICP_FILING_URL,
  resolveIcpFilingNumber,
} from "../../config/icpFiling";

describe("resolveIcpFilingNumber", () => {
  it("returns product default when env unset", () => {
    expect(resolveIcpFilingNumber(undefined)).toBe(DEFAULT_ICP_FILING_NUMBER);
  });

  it("hides when env is empty string", () => {
    expect(resolveIcpFilingNumber("")).toBeNull();
  });

  it("uses trimmed custom value", () => {
    expect(resolveIcpFilingNumber("  京ICP备123号-1  ")).toBe("京ICP备123号-1");
  });
});

describe("IcpFilingFooter", () => {
  it("renders link text and beian href", () => {
    render(<IcpFilingFooter number={DEFAULT_ICP_FILING_NUMBER} />);
    const link = screen.getByTestId("icp-filing-link");
    expect(link).toHaveTextContent(DEFAULT_ICP_FILING_NUMBER);
    expect(link).toHaveAttribute("href", ICP_FILING_URL);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
  });

  it("renders nothing when disabled", () => {
    const { container } = render(<IcpFilingFooter number="" />);
    expect(container).toBeEmptyDOMElement();
  });
});
