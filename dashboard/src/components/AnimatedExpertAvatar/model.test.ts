import { describe, expect, it } from "vitest";
import atlas from "./atlas.json";
import {
  EXPERT_CHARACTERS,
  EXPERT_PHASES,
  animationClip,
  characterUrl,
  lifecyclePhase,
  resolveCharacter,
} from "./model";

describe("expert animation assets", () => {
  it("has a valid clip for every character and action", () => {
    for (const species of EXPERT_CHARACTERS)
      for (const phase of EXPERT_PHASES) {
        const clip = animationClip(phase, species);
        expect(clip.frames.length).toBe(clip.holds.length);
        expect(clip.holds.every((ms) => ms > 0)).toBe(true);
        for (const index of clip.frames) {
          const frame = atlas[species].frames[index];
          expect(frame).toBeDefined();
          expect(frame.clip).toMatch(/^M/);
          expect(frame.w).toBeGreaterThan(0);
          expect(frame.h).toBeGreaterThan(0);
        }
      }
  });
  it("recognizes bundled and selected characters without replacing custom uploads", () => {
    expect(resolveCharacter("/experts/avatars/scene-tech.svg")).toBe("fox");
    expect(resolveCharacter("/experts/avatars/office-automation.svg")).toBe(
      "penguin",
    );
    for (const species of EXPERT_CHARACTERS)
      expect(resolveCharacter(characterUrl(species))).toBe(species);
    for (const url of [
      "/api/agents/expert/avatar?v=1",
      "https://example.org/experts/avatars/scene-tech.svg",
      "blob:portrait",
      "/experts/avatars/unknown.svg",
    ])
      expect(resolveCharacter(url)).toBeNull();
  });
  it("preserves the supplied rabbit and red panda sprite exceptions", () => {
    expect(animationClip("success", "rabbit").frames).toEqual([21]);
    expect(animationClip("handoff", "rabbit").frames).toEqual([22]);
    expect(animationClip("coding", "redpanda").frames).toEqual([14]);
  });
  it("maps actual runtime and connection states", () => {
    expect(lifecyclePhase("running", true)).toBe("offline");
    expect(lifecyclePhase("failed")).toBe("error");
    expect(lifecyclePhase("stopped")).toBe("resting");
    expect(lifecyclePhase("starting")).toBe("recovering");
  });
});
