const API_PREFIX = '/api/v1';

export const API_URLS = {
    AUTH: {
        LOGIN: `${API_PREFIX}/auth/login`,
        REGISTER: `${API_PREFIX}/auth/register`,
        REFRESH_TOKEN: `${API_PREFIX}/auth/refresh`,
        SMS_SEND: `${API_PREFIX}/auth/sms/send`,
        SMS_LOGIN: `${API_PREFIX}/auth/sms/login`,
        GOOGLE_URL: `${API_PREFIX}/auth/google/url`,
        GOOGLE_CALLBACK: `${API_PREFIX}/auth/google/callback`,
    },
    USER: {
        PROFILE: `${API_PREFIX}/users/profile`,
        LIST: `${API_PREFIX}/users/list`,
        ME: `${API_PREFIX}/users/me`,
        CSV_UPLOAD: `${API_PREFIX}/users/csv_upload`,
        QUERY: `${API_PREFIX}/users`,
        UPDATE: (id: string | number) => `${API_PREFIX}/users/${id}`,
    },
    CHAT: {
        QUERY: `${API_PREFIX}/chat/query_sent`,
        QUERY_STREAM: `${API_PREFIX}/chat/query_stream`,
        SESSIONS: `${API_PREFIX}/chat/sessions`,
        SESSION_DETAIL: (id: string) => `${API_PREFIX}/chat/sessions/${id}`,
    },
    TELEMETRY: {
        ERRORS: `${API_PREFIX}/telemetry/errors`,
    },
    KNOWLEDGE: {
        DEFAULT: `${API_PREFIX}/knowledge/default`,
    },
} as const;
