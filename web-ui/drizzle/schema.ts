import { sqliteTable, text, integer } from "drizzle-orm/sqlite-core";

/**
 * Core user table backing auth flow.
 * Extend this file with additional tables as your product grows.
 * Columns use camelCase to match both database fields and generated types.
 */
export const users = sqliteTable("users", {
  id: text("id").primaryKey(),
  name: text("name"),
  email: text("email"),
  loginMethod: text("loginMethod"),
  role: text("role", { enum: ["user", "admin"] }).default("user").notNull(),
  createdAt: integer("createdAt", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),
  lastSignedIn: integer("lastSignedIn", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

// GRAPE Configuration Tables
export const configurations = sqliteTable("configurations", {
  id: text("id").primaryKey(),
  userId: text("userId").notNull(),
  name: text("name").notNull(),
  callsign: text("callsign").notNull(),
  gridSquare: text("gridSquare").notNull(),
  stationId: text("stationId").notNull(), // PSWS SITE_ID
  instrumentId: text("instrumentId").notNull(),
  description: text("description"),
  dataDir: text("dataDir"),
  archiveDir: text("archiveDir"),
  pswsEnabled: text("pswsEnabled", { enum: ["yes", "no"] }).default("no").notNull(),
  pswsServer: text("pswsServer").default("pswsnetwork.eng.ua.edu"),
  createdAt: integer("createdAt", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),
  updatedAt: integer("updatedAt", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),
});

export const channels = sqliteTable("channels", {
  id: text("id").primaryKey(),
  configId: text("configId").notNull(),
  enabled: text("enabled", { enum: ["yes", "no"] }).default("yes").notNull(),
  description: text("description").notNull(),
  frequencyHz: text("frequencyHz").notNull(), // Store as string to avoid precision issues
  ssrc: text("ssrc").notNull(),
  sampleRate: text("sampleRate").default("12000"),
  processor: text("processor").default("grape"),
  createdAt: integer("createdAt", { mode: "timestamp" }).notNull().$defaultFn(() => new Date()),
});

export type Configuration = typeof configurations.$inferSelect;
export type InsertConfiguration = typeof configurations.$inferInsert;
export type Channel = typeof channels.$inferSelect;
export type InsertChannel = typeof channels.$inferInsert;

