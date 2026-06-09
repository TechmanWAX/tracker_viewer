import { api } from './client';
import type { User, UserRegisterPayload } from '../types/api';

interface BackendUser {
  user_id: string;
  email: string;
  username: string;
  is_active?: boolean;
  is_verified?: boolean;
  verified_at?: string | null;
  created_at?: string | null;
}

function toUser(u: BackendUser): User {
  return {
    id: u.user_id,
    email: u.email,
    username: u.username,
    isActive: u.is_active,
    isVerified: u.is_verified,
    verifiedAt: u.verified_at ?? null,
    createdAt: u.created_at ?? null,
  };
}

export interface RegisterResponse {
  user: User;
  message: string;
  /**
   * In dev (`MAIL_ENABLED=false`) the backend includes the full
   * verification URL directly in the response so the developer
   * doesn't have to dig through /tmp/verification_emails/.
   * In production this field is absent.
   */
  dev_verification_url?: string;
}

export interface VerifyEmailResponse {
  user: User;
  message: string;
}

export type VerifyEmailErrorCode = 'invalid' | 'expired' | 'used';

export interface VerifyEmailErrorBody {
  code: VerifyEmailErrorCode;
  message: string;
}

export interface ResendVerificationResponse {
  message: string;
}

/**
 * Error class for "this user must verify their email" responses.
 * The HTTP layer in `api/client.ts` keeps the response on the
 * error so we can inspect `status` and `data.detail`. We use this
 * subclass so callers can do `if (err instanceof EmailNotVerified)`
 * without reaching into the Axios details.
 */
export class EmailNotVerifiedError extends Error {
  status = 403;
  constructor(message: string) {
    super(message);
    this.name = 'EmailNotVerifiedError';
  }
}

export async function register(payload: UserRegisterPayload): Promise<RegisterResponse> {
  const { data } = await api.post<{
    user: BackendUser;
    message: string;
    dev_verification_url?: string;
  }>('/auth/register', payload);
  return {
    user: toUser(data.user),
    message: data.message,
    dev_verification_url: data.dev_verification_url,
  };
}

export async function login(email: string, password: string): Promise<User> {
  try {
    const { data } = await api.post<{ user: BackendUser }>('/auth/login', { email, password });
    return toUser(data.user);
  } catch (e: unknown) {
    // Surface "needs verification" as a typed error so the login
    // page can offer a "resend" button.
    const status = (e as { response?: { status?: number } })?.response?.status;
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    if (status === 403) {
      throw new EmailNotVerifiedError(
        typeof detail === 'string'
          ? detail
          : 'Please verify your email before signing in.',
      );
    }
    throw e;
  }
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout');
}

export async function me(): Promise<User> {
  const { data } = await api.get<{ user: BackendUser }>('/auth/me');
  return toUser(data.user);
}

/**
 * Consume a single-use verification token from the link the user
 * clicked. Throws an Error with `.code` set to one of
 * `VerifyEmailErrorCode` on failure.
 */
export async function verifyEmail(token: string): Promise<VerifyEmailResponse> {
  try {
    const { data } = await api.post<{ user: BackendUser; message: string }>(
      '/auth/verify-email',
      { token },
    );
    return { user: toUser(data.user), message: data.message };
  } catch (e: unknown) {
    const status = (e as { response?: { status?: number } })?.response?.status;
    const detail = (e as { response?: { data?: { detail?: { code?: string; message?: string } } } })?.response?.data?.detail;
    if (status === 400 && detail && typeof detail === 'object' && 'code' in detail) {
      const err = new Error(detail.message ?? 'Verification failed');
      (err as { code?: string }).code = detail.code;
      throw err;
    }
    throw e;
  }
}

export async function resendVerification(email: string): Promise<ResendVerificationResponse> {
  // Always returns 200 with the same message — never throws on
  // "no such email" so callers can't enumerate registered users.
  const { data } = await api.post<{ message: string }>('/auth/resend-verification', { email });
  return { message: data.message };
}
