import { authHandlers } from './handlers/auth';
import { userHandlers } from './handlers/users';
import { chatHandlers } from './handlers/chat';
import { creditHandlers } from './handlers/credits';

export const handlers = [
    ...authHandlers,
    ...userHandlers,
    ...chatHandlers,
    ...creditHandlers,
];
