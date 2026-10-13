import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExpertIcon } from "./iconForName";

describe("expert portrait rendering", () => {
  it("renders both builtin and selected characters as a cropped SVG", () => {
    const { container, rerender } = render(
      <ExpertIcon iconUrl="/experts/avatars/scene-design.svg" size={32} />,
    );
    expect(container.querySelector("[data-species]")).toHaveAttribute(
      "data-species",
      "rabbit",
    );
    expect(container.querySelector("svg image")).toHaveAttribute(
      "href",
      "/expert-animations/rabbit.webp",
    );
    expect(
      container.querySelector("svg image")?.getAttribute("clip-path"),
    ).toMatch(/^url\(#/);
    expect(container.querySelector("img")).toBeNull();
    rerender(
      <ExpertIcon
        iconUrl="/expert-animations/owl.webp"
        phase="reading"
        size={32}
      />,
    );
    expect(container.querySelector("[data-phase]")).toHaveAttribute(
      "data-phase",
      "reading",
    );
  });
  it("preserves a custom external portrait", () => {
    const { container } = render(
      <ExpertIcon iconUrl="https://example.com/my-avatar.png" size={32} />,
    );
    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "https://example.com/my-avatar.png",
    );
    expect(container.querySelector("[data-species]")).toBeNull();
  });
});
