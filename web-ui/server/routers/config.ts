import { z } from "zod";
import { protectedProcedure, router } from "../_core/trpc";
import * as db from "../db";
import { randomBytes } from "crypto";

// Validation schemas
const gridSquareSchema = z.string().regex(/^[A-R]{2}[0-9]{2}[a-x]{2}$/i, "Invalid grid square format (expected: AA00aa)");
const siteIdSchema = z.string().regex(/^S\d{6}$/, "Invalid SITE_ID format (expected: S000NNN)");

export const configRouter = router({
  // List all configurations for current user
  list: protectedProcedure.query(async ({ ctx }) => {
    return db.getConfigurations(ctx.user.id);
  }),

  // Get single configuration with channels
  get: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      const config = await db.getConfiguration(input.id);
      if (!config) return null;
      
      const channels = await db.getChannels(input.id);
      return { ...config, channels };
    }),

  // Create new configuration
  create: protectedProcedure
    .input(z.object({
      name: z.string().min(1, "Name is required"),
      callsign: z.string().min(1, "Callsign is required").max(20),
      gridSquare: gridSquareSchema,
      stationId: siteIdSchema,
      instrumentId: z.string().min(1, "Instrument ID is required"),
      description: z.string().optional(),
      dataDir: z.string().optional(),
      archiveDir: z.string().optional(),
      pswsEnabled: z.enum(["yes", "no"]).default("no"),
      pswsServer: z.string().default("pswsnetwork.eng.ua.edu"),
    }))
    .mutation(async ({ ctx, input }) => {
      const id = randomBytes(16).toString("hex");
      await db.createConfiguration({
        id,
        userId: ctx.user.id,
        ...input,
      });
      return { id };
    }),

  // Update configuration
  update: protectedProcedure
    .input(z.object({
      id: z.string(),
      name: z.string().min(1).optional(),
      callsign: z.string().min(1).max(20).optional(),
      gridSquare: gridSquareSchema.optional(),
      stationId: siteIdSchema.optional(),
      instrumentId: z.string().min(1).optional(),
      description: z.string().optional(),
      dataDir: z.string().optional(),
      archiveDir: z.string().optional(),
      pswsEnabled: z.enum(["yes", "no"]).optional(),
      pswsServer: z.string().optional(),
    }))
    .mutation(async ({ input }) => {
      const { id, ...updates } = input;
      await db.updateConfiguration(id, updates);
      return { success: true };
    }),

  // Delete configuration
  delete: protectedProcedure
    .input(z.object({ id: z.string() }))
    .mutation(async ({ input }) => {
      await db.deleteConfiguration(input.id);
      return { success: true };
    }),

  // Export configuration as TOML
  exportToml: protectedProcedure
    .input(z.object({ id: z.string() }))
    .query(async ({ input }) => {
      const config = await db.getConfiguration(input.id);
      if (!config) throw new Error("Configuration not found");
      
      const channels = await db.getChannels(input.id);
      
      // Generate TOML format
      let toml = `[station]\n`;
      toml += `callsign = "${config.callsign}"\n`;
      toml += `grid_square = "${config.gridSquare}"\n`;
      toml += `id = "${config.stationId}"\n`;
      toml += `instrument_id = "${config.instrumentId}"\n`;
      if (config.description) {
        toml += `description = "${config.description}"\n`;
      }
      toml += `\n`;
      
      toml += `[ka9q]\n`;
      toml += `auto_create_channels = true\n`;
      toml += `\n`;
      
      toml += `[recorder]\n`;
      if (config.dataDir) {
        toml += `data_dir = "${config.dataDir}"\n`;
      }
      if (config.archiveDir) {
        toml += `archive_dir = "${config.archiveDir}"\n`;
      }
      toml += `recording_interval = 60\n`;
      toml += `continuous = true\n`;
      toml += `\n`;
      
      if (config.pswsEnabled === "yes") {
        toml += `[psws]\n`;
        toml += `server = "${config.pswsServer}"\n`;
        toml += `site_id = "${config.stationId}"\n`;
        toml += `instrument_id = "${config.instrumentId}"\n`;
        toml += `enabled = true\n`;
        toml += `\n`;
      }
      
      // Add channels
      for (const channel of channels) {
        toml += `[[recorder.channels]]\n`;
        toml += `ssrc = ${channel.ssrc}\n`;
        toml += `frequency_hz = ${channel.frequencyHz}\n`;
        toml += `sample_rate = ${channel.sampleRate}\n`;
        toml += `description = "${channel.description}"\n`;
        toml += `enabled = ${channel.enabled === "yes" ? "true" : "false"}\n`;
        toml += `processor = "${channel.processor}"\n`;
        toml += `preset = "iq"\n`;
        toml += `\n`;
      }
      
      return { toml };
    }),
});

