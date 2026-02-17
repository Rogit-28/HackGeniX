// ============================================================
// Auth utilities — JWT generation (dev mode) + token storage
// ============================================================
// NOTE: JWT signing uses jsonwebtoken which is Node.js only.
// Token generation happens in a Next.js API route (/api/auth/token).
// Client-side code only stores/retrieves tokens from localStorage.

import { type AuthUser, type Role, ROLE_PERMISSIONS } from './types';

const TOKEN_KEY = 'hackgenix_token';
const USER_KEY = 'hackgenix_user';

// --- Client-side token/user storage ---

export function getStoredUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    const user = JSON.parse(raw) as AuthUser;
    // Check if token is expired (decode payload without verification)
    const payload = JSON.parse(atob(user.token.split('.')[1]));
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      clearStoredUser();
      return null;
    }
    return user;
  } catch {
    clearStoredUser();
    return null;
  }
}

export function storeUser(user: AuthUser): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, user.token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearStoredUser(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getStoredToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getPermissionsForRole(role: Role): string[] {
  return ROLE_PERMISSIONS[role] || [];
}
