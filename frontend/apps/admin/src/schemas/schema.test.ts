import { chatStreamEventSchema, chatSessionSchema, chatMessageSchema } from './chat';
import { userRegistrationPayloadSchema } from './user';

describe('schema layer', () => {
    it('validates user registration payloads before requests are sent', () => {
        const result = userRegistrationPayloadSchema.safeParse({
            username: 'alice',
            email: 'alice@example.com',
            password: 'password123',
            confirm_password: 'password123',
            max_tokens: 100000,
        });

        expect(result.success).toBe(true);
    });

    it('parses chat stream meta events from the backend', () => {
        const result = chatStreamEventSchema.safeParse({
            type: 'meta',
            session_id: 'session-1',
            session_title: 'Hello',
            message_id: 'message-1',
        });

        expect(result.success).toBe(true);
    });

    it('successfully parses chatSessionSchema when kb_id is null', () => {
        const result = chatSessionSchema.safeParse({
            id: 's1',
            title: 'Test Session',
            user_id: 'u1',
            kb_id: null,
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        expect(result.success).toBe(true);
    });

    it('successfully parses chatMessageSchema when latency_ms and search_context are null', () => {
        const result = chatMessageSchema.safeParse({
            id: 'm1',
            session_id: 's1',
            role: 'assistant',
            content: 'Hello world',
            status: 'success',
            latency_ms: null,
            search_context: null,
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        expect(result.success).toBe(true);
    });
});
