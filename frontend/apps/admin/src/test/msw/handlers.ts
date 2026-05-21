import { authHandlers } from './handlers/auth';
import { userHandlers } from './handlers/users';
import { chatHandlers } from './handlers/chat';

export const handlers = [
    ...authHandlers,
    ...userHandlers,
    ...chatHandlers,
];
