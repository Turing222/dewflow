import {
    chatMessageSchema,
    chatSessionSchema,
    chatStreamEventSchema,
    searchContextSchema,
} from './chat';
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

    it('parses chat message and RAG metrics when present', () => {
        const message = chatMessageSchema.parse({
            id: 'm1',
            session_id: 's1',
            role: 'assistant',
            content: 'Hello world',
            status: 'success',
            latency_ms: 123,
            search_context: {
                metrics: {
                    retrieve_ms: 42,
                    hit_count: 4,
                    retrieval_mode: 'hybrid',
                    rerank_used: true,
                },
            },
            message_metadata: {
                metrics: {
                    first_token_latency_ms: 250,
                    tokens_per_second: 12.5,
                },
            },
            created_at: '2026-05-21T12:00:00Z',
            updated_at: '2026-05-21T12:00:00Z',
        });
        const searchContext = searchContextSchema.parse(message.search_context);

        expect(message.message_metadata?.metrics).toEqual({
            first_token_latency_ms: 250,
            tokens_per_second: 12.5,
        });
        expect(searchContext.metrics?.retrieval_mode).toBe('hybrid');
    });
});
