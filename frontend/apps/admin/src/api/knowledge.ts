import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { 
    knowledgeBaseResponseSchema,
    knowledgeUploadResponseSchema,
    kbTaskResponseSchema
} from '../schemas/chat';
import { API_URLS } from './urls';
import { resolveIdempotencyKey, IDEMPOTENCY_KEY_HEADER } from '../lib/http/idempotency';

export const getDefaultKBAPI = () => {
    return request
        .get<unknown, unknown>(API_URLS.KNOWLEDGE.DEFAULT)
        .then((response) =>
            parseWithSchema(
                knowledgeBaseResponseSchema,
                response,
                '获取默认知识库响应格式无效',
            ),
        );
};

export const uploadKBFileAPI = (file: File, idempotencyKey?: string) => {
    const resolvedKey = resolveIdempotencyKey(idempotencyKey);
    const formData = new FormData();
    formData.append('file', file);
    return request
        .post<unknown, unknown>(API_URLS.KNOWLEDGE.DEFAULT_UPLOAD, formData, {
            headers: {
                [IDEMPOTENCY_KEY_HEADER]: resolvedKey,
            },
        })
        .then((response) =>
            parseWithSchema(
                knowledgeUploadResponseSchema,
                response,
                '文件上传响应格式无效',
            ),
        );
};

export const getKBTaskStatusAPI = (taskId: string) => {
    return request
        .get<unknown, unknown>(API_URLS.KNOWLEDGE.TASK_STATUS(taskId))
        .then((response) =>
            parseWithSchema(
                kbTaskResponseSchema,
                response,
                '获取任务状态响应格式无效',
            ),
        );
};
