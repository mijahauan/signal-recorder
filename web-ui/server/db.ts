import { eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/better-sqlite3";
import Database from "better-sqlite3";
import { InsertUser, users, configurations, InsertConfiguration, channels, InsertChannel } from "../drizzle/schema";
import { ENV } from './_core/env';
import { mkdirSync } from "fs";
import { dirname } from "path";

let _db: ReturnType<typeof drizzle> | null = null;

// Lazily create the drizzle instance so local tooling can run without a DB.
export async function getDb() {
  if (!_db) {
    try {
      // Default to ./data/grape-config.db if DATABASE_URL not set
      const dbPath = process.env.DATABASE_URL?.replace('file:', '') || './data/grape-config.db';
      
      // Ensure directory exists
      mkdirSync(dirname(dbPath), { recursive: true });
      
      // Create SQLite connection
      const sqlite = new Database(dbPath);
      _db = drizzle(sqlite);
      
      console.log(`[Database] Connected to SQLite: ${dbPath}`);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}

export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.id) {
    throw new Error("User ID is required for upsert");
  }

  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }

  try {
    // Check if user exists
    const existing = await db.select().from(users).where(eq(users.id, user.id)).limit(1);
    
    if (existing.length > 0) {
      // Update existing user
      const updateData: Partial<InsertUser> = {};
      
      if (user.name !== undefined) updateData.name = user.name;
      if (user.email !== undefined) updateData.email = user.email;
      if (user.loginMethod !== undefined) updateData.loginMethod = user.loginMethod;
      if (user.lastSignedIn !== undefined) updateData.lastSignedIn = user.lastSignedIn;
      
      // Set role to admin if user is owner
      if (user.id === ENV.ownerId) {
        updateData.role = 'admin';
      } else if (user.role !== undefined) {
        updateData.role = user.role;
      }
      
      if (Object.keys(updateData).length > 0) {
        await db.update(users).set(updateData).where(eq(users.id, user.id));
      }
    } else {
      // Insert new user
      const insertData: InsertUser = {
        id: user.id,
        name: user.name ?? null,
        email: user.email ?? null,
        loginMethod: user.loginMethod ?? null,
        role: user.id === ENV.ownerId ? 'admin' : (user.role ?? 'user'),
        createdAt: new Date(),
        lastSignedIn: user.lastSignedIn ?? new Date(),
      };
      
      await db.insert(users).values(insertData);
    }
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}

export async function getUser(id: string) {
  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot get user: database not available");
    return undefined;
  }

  const result = await db.select().from(users).where(eq(users.id, id)).limit(1);

  return result.length > 0 ? result[0] : undefined;
}

// Configuration queries
export async function getConfigurations(userId: string) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(configurations).where(eq(configurations.userId, userId));
}

export async function getConfiguration(id: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(configurations).where(eq(configurations.id, id)).limit(1);
  return result[0];
}

export async function createConfiguration(config: InsertConfiguration) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.insert(configurations).values(config);
}

export async function updateConfiguration(id: string, config: Partial<InsertConfiguration>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(configurations).set({ ...config, updatedAt: new Date() }).where(eq(configurations.id, id));
}

export async function deleteConfiguration(id: string) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  // Delete associated channels first
  await db.delete(channels).where(eq(channels.configId, id));
  await db.delete(configurations).where(eq(configurations.id, id));
}

// Channel queries
export async function getChannels(configId: string) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(channels).where(eq(channels.configId, configId));
}

export async function createChannel(channel: InsertChannel) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.insert(channels).values(channel);
}

export async function updateChannel(id: string, channel: Partial<InsertChannel>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(channels).set(channel).where(eq(channels.id, id));
}

export async function deleteChannel(id: string) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.delete(channels).where(eq(channels.id, id));
}

