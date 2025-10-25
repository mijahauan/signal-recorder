import { z } from "zod";
import { protectedProcedure, router } from "../_core/trpc";
import * as db from "../db";
import { randomBytes } from "crypto";

// Channel presets
const WWV_CHANNELS = [
  { freq: 2500000, desc: "WWV 2.5 MHz" },
  { freq: 5000000, desc: "WWV 5 MHz" },
  { freq: 10000000, desc: "WWV 10 MHz" },
  { freq: 15000000, desc: "WWV 15 MHz" },
  { freq: 20000000, desc: "WWV 20 MHz" },
  { freq: 25000000, desc: "WWV 25 MHz" },
];

const CHU_CHANNELS = [
  { freq: 3330000, desc: "CHU 3.33 MHz" },
  { freq: 7850000, desc: "CHU 7.85 MHz" },
  { freq: 14670000, desc: "CHU 14.67 MHz" },
];

export const channelRouter = router({
  // List channels for a configuration
  list: protectedProcedure
    .input(z.object({ configId: z.string() }))
    .query(async ({ input }) => {
      return db.getChannels(input.configId);
    }),

  // Create channel
  create: protectedProcedure
    .input(z.object({
      configId: z.string(),
      enabled: z.enum(["yes", "no"]).default("yes"),
      description: z.string().min(1, "Description is required"),
      frequencyHz: z.string().min(1, "Frequency is required"),
      ssrc: z.string().min(1, "SSRC is required"),
      sampleRate: z.string().default("12000"),
      processor: z.string().default("grape"),
    }))
    .mutation(async ({ input }) => {
      const id = randomBytes(16).toString("hex");
      await db.createChannel({ id, ...input });
      return { id };
    }),

  // Update channel
  update: protectedProcedure
    .input(z.object({
      id: z.string(),
      enabled: z.enum(["yes", "no"]).optional(),
      description: z.string().min(1).optional(),
      frequencyHz: z.string().min(1).optional(),
      ssrc: z.string().min(1).optional(),
      sampleRate: z.string().optional(),
      processor: z.string().optional(),
    }))
    .mutation(async ({ input }) => {
      const { id, ...updates } = input;
      await db.updateChannel(id, updates);
      return { success: true };
    }),

  // Delete channel
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input }) => {
      await db.deleteChannel(input.id);
      return { success: true };
    }),

  // Apply preset (WWV or CHU)
  applyPreset: protectedProcedure
    .input(z.object({
      configId: z.string(),
      preset: z.enum(["wwv", "chu", "both"]),
    }))
    .mutation(async ({ input }) => {
      const channels = input.preset === "wwv" ? WWV_CHANNELS :
                      input.preset === "chu" ? CHU_CHANNELS :
                      [...WWV_CHANNELS, ...CHU_CHANNELS];
      
      const created = [];
      for (const channel of channels) {
        const id = randomBytes(16).toString("hex");
        await db.createChannel({
          id,
          configId: input.configId,
          enabled: "yes",
          description: channel.desc,
          frequencyHz: channel.freq.toString(),
          ssrc: channel.freq.toString(), // Use frequency as SSRC
          sampleRate: "12000",
          processor: "grape",
        });
        created.push(id);
      }
      
      return { created: created.length };
    }),

  // Get presets info
  getPresets: protectedProcedure.query(() => {
    return {
      wwv: WWV_CHANNELS,
      chu: CHU_CHANNELS,
    };
  }),
});

