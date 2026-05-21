import request from '../lib/http/client';
import { parseWithSchema } from '../schemas/parse';
import { knowledgeBaseResponseSchema } from '../schemas/chat';
import { API_URLS } from './urls';

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
