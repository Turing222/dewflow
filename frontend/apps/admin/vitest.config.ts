import react from '@vitejs/plugin-react';
import { defineConfig, configDefaults } from 'vitest/config';

export default defineConfig({
    plugins: [react()],
    server: {
        watch: {
            ignored: [
                '**/node_modules/**',
                '**/dist/**',
                '**/e2e/**',
                '**/playwright-report/**',
                '**/test-results/**',
                '**/backend/**',
                '**/logs/**',
                '**/.git/**',
                '**/.cache/**',
                '**/.pytest_cache/**',
                '**/.venv/**',
            ],
        },
    },
    test: {
        environment: 'jsdom',
        globals: true,
        css: true,
        setupFiles: ['./src/test/setup.ts'],
        exclude: [
            ...configDefaults.exclude,
            '**/e2e/**',
            '**/backend/**',
            '**/logs/**',
        ],
        testTimeout: 30000,
        hookTimeout: 30000,
        teardownTimeout: 30000,
        poolOptions: {
            threads: {
                singleThread: true,
            },
            forks: {
                singleFork: true,
            },
        },
    },
});
