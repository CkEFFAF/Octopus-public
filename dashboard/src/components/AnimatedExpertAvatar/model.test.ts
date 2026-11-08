import { describe, expect, it } from "vitest";
import {
  EXPERT_CHARACTERS,
  EXPERT_PHASES,
  GIF_CLIPS,
  animationUrl,
  characterUrl,
  gifClip,
  lifecyclePhase,
  resolveCharacter,
} from "./model";
describe("GIF expert identities", () => {
  it("covers every runtime phase with one of eight clips for all fifteen characters", () => {
    expect(EXPERT_CHARACTERS).toHaveLength(15);
    for (const character of EXPERT_CHARACTERS)
      for (const phase of EXPERT_PHASES) {
        expect(GIF_CLIPS).toContain(gifClip(phase));
        expect(animationUrl(character, phase)).toBe(
          `/expert-animations/v2/${character}/${gifClip(phase)}.gif`,
        );
        expect(animationUrl(character, phase, false)).toMatch(/\.png$/);
      }
  });
  it("keeps old saved identities and custom uploads compatible", () => {
    for (const character of EXPERT_CHARACTERS) {
      expect(resolveCharacter(characterUrl(character))).toBe(character);
      expect(resolveCharacter(animationUrl(character, "coding"))).toBe(
        character,
      );
    }
    expect(resolveCharacter("/experts/avatars/scene-tech.svg")).toBe("fox");
    expect(resolveCharacter("/api/agents/custom/avatar?v=1")).toBeNull();
    expect(
      resolveCharacter("https://example.org/expert-animations/fox.webp"),
    ).toBeNull();
  });
  it("keeps lifecycle failures and offline states authoritative", () => {
    expect(lifecyclePhase("running", true)).toBe("offline");
    expect(lifecyclePhase("failed")).toBe("error");
    expect(lifecyclePhase("stopped")).toBe("resting");
  });
});
