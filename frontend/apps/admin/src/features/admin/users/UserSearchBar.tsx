import React from 'react';
import { Button, Input, Space, Upload } from 'antd';
import { Search, UserPlus, Upload as UploadIcon } from 'lucide-react';
import type { UploadProps } from 'antd';

type UserSearchBarProps = {
    searchValue: string;
    onSearchValueChange: (v: string) => void;
    onSearch: () => void;
    onCreateClick: () => void;
    onUpload: (file: File) => Promise<boolean>;
};

const UserSearchBar: React.FC<UserSearchBarProps> = ({
    searchValue,
    onSearchValueChange,
    onSearch,
    onCreateClick,
    onUpload,
}) => {
    const uploadProps: UploadProps = {
        showUploadList: false,
        beforeUpload: onUpload,
        accept: '.csv,.xlsx,.xls',
    };

    return (
        <Space>
            <Input.Search
                placeholder="搜索用户名或邮箱"
                value={searchValue}
                onChange={(e) => onSearchValueChange(e.target.value)}
                onSearch={onSearch}
                enterButton={<Search size={14} />}
                style={{ width: 280 }}
                allowClear
            />
            <Button
                type="primary"
                icon={<UserPlus size={14} />}
                onClick={onCreateClick}
            >
                新建用户
            </Button>
            <Upload {...uploadProps}>
                <Button icon={<UploadIcon size={14} />}>批量导入</Button>
            </Upload>
        </Space>
    );
};

export default UserSearchBar;
