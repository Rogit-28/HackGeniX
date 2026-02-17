// ============================================================
// API Route: POST /api/auth/token
// Dev-mode JWT generation (server-side, uses jsonwebtoken)
// Body: { userId: string, role: Role }
// Returns: { token: string, user: AuthUser }
// ============================================================

import { NextRequest, NextResponse } from 'next/server';
import jwt from 'jsonwebtoken';
import { type Role, ROLE_PERMISSIONS } from '@/lib/types';

const JWT_SECRET = process.env.JWT_SECRET_KEY || 'rogit_hackgenix';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { userId, role } = body as { userId: string; role: Role };

    if (!userId || !role) {
      return NextResponse.json(
        { error: 'userId and role are required' },
        { status: 400 }
      );
    }

    const permissions = ROLE_PERMISSIONS[role];
    if (!permissions) {
      return NextResponse.json(
        { error: `Invalid role: ${role}` },
        { status: 400 }
      );
    }

    const token = jwt.sign(
      {
        sub: userId,
        role: role,
        permissions: permissions,
        type: 'access',
      },
      JWT_SECRET,
      { algorithm: 'HS256', expiresIn: '2h' }
    );

    return NextResponse.json({
      token,
      user: {
        id: userId,
        role,
        permissions,
        token,
      },
    });
  } catch (error) {
    console.error('Token generation error:', error);
    return NextResponse.json(
      { error: 'Failed to generate token' },
      { status: 500 }
    );
  }
}
