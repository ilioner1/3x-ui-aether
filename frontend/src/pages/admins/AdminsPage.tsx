import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router';
import {
  Button,
  Card,
  ConfigProvider,
  Form,
  Input,
  InputNumber,
  Layout,
  Modal,
  Popconfirm,
  Progress,
  Result,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import { EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';

import AppSidebar from '@/layouts/AppSidebar';
import { useTheme } from '@/hooks/useTheme';
import { HttpUtil, SizeFormatter } from '@/utils';

const API = '/panel/delegated-admins';
const GIB = 1024 ** 3;

interface AdminAccount {
  id: number;
  username: string;
  groupId: number;
  enabled: boolean;
  quotaBytes: number;
  usedBytes: number;
}

interface AdminGroup {
  ID: number;
  Name: string;
}

interface AdminData {
  accounts: AdminAccount[];
  groups: AdminGroup[];
  grants: { GroupID: number; InboundID: number }[];
  inbounds: { id: number; remark: string; protocol: string }[];
}

interface AccountForm {
  username: string;
  password?: string;
  group: number;
  quota: number;
  enable: boolean;
}

interface GroupForm {
  name: string;
  inbound?: number[];
}

export default function AdminsPage() {
  const { pathname } = useLocation();
  const reports = pathname === '/admins-reports';
  const { antdThemeConfig, isDark, isUltra } = useTheme();
  const [messageApi, messageContext] = message.useMessage();
  const [accountForm] = Form.useForm<AccountForm>();
  const [groupForm] = Form.useForm<GroupForm>();
  const [account, setAccount] = useState<AdminAccount | null>();
  const [group, setGroup] = useState<AdminGroup | null>();
  const [saving, setSaving] = useState(false);

  const data = useQuery({
    queryKey: ['delegated-admins'],
    queryFn: async () => {
      const result = await HttpUtil.get<AdminData>(API + '/data');
      if (!result?.success || !result.obj) throw new Error(result?.msg || 'Could not load admins');
      return result.obj;
    },
    refetchInterval: 5000,
  });

  const groups = data.data?.groups ?? [];
  const accounts = data.data?.accounts ?? [];
  const inbounds = data.data?.inbounds ?? [];
  const base = window.X_UI_BASE_PATH || '/';

  function editAccount(item: AdminAccount | null) {
    accountForm.resetFields();
    accountForm.setFieldsValue({
      username: item?.username || '',
      password: '',
      group: item?.groupId,
      quota: item ? item.quotaBytes / GIB : 200,
      enable: item?.enabled ?? true,
    });
    setAccount(item);
  }

  function editGroup(item: AdminGroup | null) {
    groupForm.resetFields();
    groupForm.setFieldsValue({
      name: item?.Name || '',
      inbound: data.data?.grants
        .filter((grant) => grant.GroupID === item?.ID)
        .map((grant) => grant.InboundID),
    });
    setGroup(item);
  }

  async function saveAccount(values: AccountForm) {
    setSaving(true);
    try {
      const result = await HttpUtil.post(API + '/account', {
        id: account?.id,
        username: values.username,
        password: values.password,
        group: values.group,
        quota: values.quota,
        enable: values.enable ? 1 : 0,
      });
      if (result?.success) {
        setAccount(undefined);
        await data.refetch();
      } else if (result?.msg) {
        messageApi.error(result.msg);
      }
    } finally {
      setSaving(false);
    }
  }

  async function saveGroup(values: GroupForm) {
    setSaving(true);
    try {
      const result = await HttpUtil.post(API + '/group', {
        id: group?.ID,
        name: values.name,
        inbound: values.inbound ?? [],
      });
      if (result?.success) {
        setGroup(undefined);
        await data.refetch();
      } else if (result?.msg) {
        messageApi.error(result.msg);
      }
    } finally {
      setSaving(false);
    }
  }

  async function resetTraffic(item: AdminAccount) {
    const result = await HttpUtil.post(API + '/reset-traffic', { id: item.id });
    if (result?.success) {
      messageApi.success('Admin usage reset');
      await data.refetch();
    }
  }

  return (
    <ConfigProvider theme={antdThemeConfig}>
      {messageContext}
      <Layout className={`groups-page${isDark ? ' is-dark' : ''}${isUltra ? ' is-ultra' : ''}`}>
        <AppSidebar />
        <Layout className="content-shell">
          <Layout.Content className="content-area">
            <Space orientation="vertical" size="large" style={{ width: '100%' }}>
              {data.isError && (
                <Result status="error" title={data.error.message} />
              )}
              <Card
                title={reports ? 'Admin Reports' : 'Admins'}
                extra={
                  !reports && (
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      disabled={groups.length === 0}
                      onClick={() => editAccount(null)}
                    >
                      Add admin
                    </Button>
                  )
                }
              >
                <Table
                  rowKey="id"
                  dataSource={accounts}
                  loading={data.isPending}
                  scroll={{ x: 760 }}
                  columns={[
                    {
                      title: 'Admin',
                      key: 'username',
                      render: (_, item) => (
                        <Space>
                          <Typography.Text strong>{item.username}</Typography.Text>
                          <Tag color={item.enabled ? 'green' : 'default'}>
                            {item.enabled ? 'Enabled' : 'Disabled'}
                          </Tag>
                        </Space>
                      ),
                    },
                    {
                      title: 'Group',
                      key: 'group',
                      render: (_, item) => groups.find((value) => value.ID === item.groupId)?.Name,
                    },
                    {
                      title: 'Usage / quota',
                      key: 'usage',
                      render: (_, item) => (
                        <Space orientation="vertical" style={{ width: '100%' }}>
                          <span>
                            {SizeFormatter.sizeFormat(item.usedBytes)} / {SizeFormatter.sizeFormat(item.quotaBytes)}
                          </span>
                          <Progress
                            percent={Math.min(100, Math.round((item.usedBytes / item.quotaBytes) * 100))}
                            size="small"
                          />
                        </Space>
                      ),
                    },
                    {
                      title: 'Actions',
                      key: 'actions',
                      render: (_, item) => (
                        <Space wrap>
                          <Link to={`/admins-clients?admin=${item.id}`}>Clients</Link>
                          {!reports && (
                            <Typography.Text copyable={{ text: new URL(`${base}delegate/?account=${encodeURIComponent(item.username)}`, window.location.origin).href }}>
                              Login link
                            </Typography.Text>
                          )}
                          <Button icon={<EditOutlined />} onClick={() => editAccount(item)}>
                            Edit
                          </Button>
                          <Popconfirm
                            title="Reset admin traffic?"
                            description="The quota limit stays the same."
                            onConfirm={() => resetTraffic(item)}
                          >
                            <Button icon={<ReloadOutlined />}>Reset traffic</Button>
                          </Popconfirm>
                        </Space>
                      ),
                    },
                  ]}
                />
              </Card>
              {!reports && (
                <Card
                  title="Admin groups"
                  extra={
                    <Button icon={<PlusOutlined />} onClick={() => editGroup(null)}>
                      Add group
                    </Button>
                  }
                >
                  <Table
                    rowKey="ID"
                    dataSource={groups}
                    pagination={false}
                    columns={[
                      { title: 'Group', dataIndex: 'Name' },
                      {
                        title: 'Inbounds',
                        key: 'inbounds',
                        render: (_, item) => (
                          <Space wrap>
                            {data.data?.grants
                              .filter((grant) => grant.GroupID === item.ID)
                              .map((grant) => (
                                <Tag key={grant.InboundID}>
                                  {inbounds.find((inbound) => inbound.id === grant.InboundID)?.remark ||
                                    grant.InboundID}
                                </Tag>
                              ))}
                          </Space>
                        ),
                      },
                      {
                        title: 'Actions',
                        key: 'actions',
                        render: (_, item) => (
                          <Button icon={<EditOutlined />} onClick={() => editGroup(item)}>
                            Edit group
                          </Button>
                        ),
                      },
                    ]}
                  />
                </Card>
              )}
            </Space>
          </Layout.Content>
        </Layout>
      </Layout>
      <Modal
        open={account !== undefined}
        title={account ? 'Edit admin' : 'Add admin'}
        okText="Save"
        confirmLoading={saving}
        onOk={() => accountForm.submit()}
        onCancel={() => setAccount(undefined)}
      >
        <Form form={accountForm} layout="vertical" onFinish={saveAccount}>
          <Form.Item label="Username" name="username" rules={[{ required: true }]}>
            <Input maxLength={64} />
          </Form.Item>
          <Form.Item label="Password" name="password" rules={[{ required: !account, min: 8 }]}>
            <Input.Password autoComplete="new-password" maxLength={72} />
          </Form.Item>
          <Form.Item label="Group" name="group" rules={[{ required: true }]}>
            <Select options={groups.map((item) => ({ value: item.ID, label: item.Name }))} />
          </Form.Item>
          <Form.Item label="Quota (GiB)" name="quota" rules={[{ required: true }]}>
            <InputNumber min={1} max={1000000} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item label="Enabled" name="enable" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        open={group !== undefined}
        title={group ? 'Edit group' : 'Add group'}
        okText="Save"
        confirmLoading={saving}
        onOk={() => groupForm.submit()}
        onCancel={() => setGroup(undefined)}
      >
        <Form form={groupForm} layout="vertical" onFinish={saveGroup}>
          <Form.Item label="Group name" name="name" rules={[{ required: true }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="Inbounds" name="inbound">
            <Select
              mode="multiple"
              options={inbounds.map((item) => ({
                value: item.id,
                label: item.remark || item.protocol + ' #' + item.id,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </ConfigProvider>
  );
}
