import { createHash } from "crypto";
import { getDb } from "./db";
import { users } from "../drizzle/schema";
import { eq } from "drizzle-orm";

/**
 * Simple local authentication for GRAPE Config UI
 * Uses SHA-256 hashing (sufficient for local single-user tool)
 */

const DEFAULT_USERNAME = "admin";
const DEFAULT_PASSWORD = "admin";

function hashPassword(password: string): string {
  return createHash("sha256").update(password).digest("hex");
}

export async function initializeDefaultUser() {
  const db = await getDb();
  if (!db) {
    console.warn("[LocalAuth] Database not available, skipping user initialization");
    return;
  }

  try {
    // Check if admin user exists
    const existing = await db
      .select()
      .from(users)
      .where(eq(users.email, DEFAULT_USERNAME))
      .limit(1);

    if (existing.length === 0) {
      // Create default admin user
      await db.insert(users).values({
        id: "local-admin",
        name: "Administrator",
        email: DEFAULT_USERNAME,
        loginMethod: "local",
        role: "admin",
      });

      console.log("[LocalAuth] Default admin user created");
      console.log(`[LocalAuth] Username: ${DEFAULT_USERNAME}`);
      console.log(`[LocalAuth] Password: ${DEFAULT_PASSWORD}`);
    }
  } catch (error) {
    console.error("[LocalAuth] Failed to initialize default user:", error);
  }
}

export async function validateCredentials(
  username: string,
  password: string
): Promise<{ id: string; name: string; email: string; role: string } | null> {
  const db = await getDb();
  if (!db) return null;

  try {
    // For simplicity, we're using the default credentials
    // In a production system, you'd store hashed passwords in the database
    if (username === DEFAULT_USERNAME && password === DEFAULT_PASSWORD) {
      const user = await db
        .select()
        .from(users)
        .where(eq(users.email, DEFAULT_USERNAME))
        .limit(1);

      if (user.length > 0) {
        return {
          id: user[0].id,
          name: user[0].name || "Administrator",
          email: user[0].email || DEFAULT_USERNAME,
          role: user[0].role || "admin",
        };
      }
    }

    return null;
  } catch (error) {
    console.error("[LocalAuth] Validation error:", error);
    return null;
  }
}

export async function getUserById(id: string) {
  const db = await getDb();
  if (!db) return null;

  try {
    const result = await db
      .select()
      .from(users)
      .where(eq(users.id, id))
      .limit(1);

    return result.length > 0 ? result[0] : null;
  } catch (error) {
    console.error("[LocalAuth] Get user error:", error);
    return null;
  }
}

