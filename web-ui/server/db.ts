import { eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import { InsertUser, users, configurations, InsertConfiguration, channels, InsertChannel } from "../drizzle/schema";
import { ENV } from './_core/env';

let _db: ReturnType<typeof drizzle> | null = null;

// Lazily create the drizzle instance so local tooling can run without a DB.
export async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
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
    const values: InsertUser = {
      id: user.id,
    };
    const updateSet: Record<string, unknown> = {};

    const textFields = ["name", "email", "loginMethod"] as const;
    type TextField = (typeof textFields)[number];

    const assignNullable = (field: TextField) => {
      const value = user[field];
      if (value === undefined) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };

    textFields.forEach(assignNullable);

    if (user.lastSignedIn !== undefined) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role === undefined) {
      if (user.id === ENV.ownerId) {
        user.role = 'admin';
        values.role = 'admin';
        updateSet.role = 'admin';
      }
    }

    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = new Date();
    }

    await db.insert(users).values(values).onDuplicateKeyUpdate({
      set: updateSet,
    });
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
