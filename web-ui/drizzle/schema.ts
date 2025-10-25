import { mysqlEnum, mysqlTable, text, timestamp, varchar } from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 * Extend this file with additional tables as your product grows.
 * Columns use camelCase to match both database fields and generated types.
 */
export const users = mysqlTable("users", {
  id: varchar("id", { length: 64 }).primaryKey(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

// GRAPE Configuration Tables
export const configurations = mysqlTable("configurations", {
  id: varchar("id", { length: 64 }).primaryKey(),
  userId: varchar("userId", { length: 64 }).notNull(),
  name: varchar("name", { length: 255 }).notNull(),
  callsign: varchar("callsign", { length: 20 }).notNull(),
  gridSquare: varchar("gridSquare", { length: 10 }).notNull(),
  stationId: varchar("stationId", { length: 20 }).notNull(), // PSWS SITE_ID
  instrumentId: varchar("instrumentId", { length: 10 }).notNull(),
  description: text("description"),
  dataDir: varchar("dataDir", { length: 500 }),
  archiveDir: varchar("archiveDir", { length: 500 }),
  pswsEnabled: mysqlEnum("pswsEnabled", ["yes", "no"]).default("no").notNull(),
  pswsServer: varchar("pswsServer", { length: 255 }).default("pswsnetwork.eng.ua.edu"),
  createdAt: timestamp("createdAt").defaultNow(),
  updatedAt: timestamp("updatedAt").defaultNow(),
});

export const channels = mysqlTable("channels", {
  id: varchar("id", { length: 64 }).primaryKey(),
  configId: varchar("configId", { length: 64 }).notNull(),
  enabled: mysqlEnum("enabled", ["yes", "no"]).default("yes").notNull(),
  description: varchar("description", { length: 255 }).notNull(),
  frequencyHz: varchar("frequencyHz", { length: 20 }).notNull(), // Store as string to avoid precision issues
  ssrc: varchar("ssrc", { length: 20 }).notNull(),
  sampleRate: varchar("sampleRate", { length: 10 }).default("12000"),
  processor: varchar("processor", { length: 50 }).default("grape"),
  createdAt: timestamp("createdAt").defaultNow(),
});

export type Configuration = typeof configurations.$inferSelect;
export type InsertConfiguration = typeof configurations.$inferInsert;
export type Channel = typeof channels.$inferSelect;
export type InsertChannel = typeof channels.$inferInsert;
