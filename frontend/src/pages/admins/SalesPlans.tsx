import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Form, Input, InputNumber, Modal, Space, Switch, Table, Tag } from 'antd';
import { HttpUtil } from '@/utils';

const API = '/panel/delegated-admins/sales';

interface PlanValues {
  name: string;
  quotaGiB: number;
  enabled: boolean;
}

interface Plan extends PlanValues {
  id: number;
}

export default function SalesPlans() {
  const [form] = Form.useForm<PlanValues>();
  const [editing, setEditing] = useState<Plan | null>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [tokenDialog, setTokenDialog] = useState<'generate' | 'revoke'>();
  const [salesToken, setSalesToken] = useState('');
  const [tokenError, setTokenError] = useState('');
  const [changingToken, setChangingToken] = useState(false);
  const tokenStatus = useQuery({
    queryKey: ['delegated-sales-token-status'],
    queryFn: async () => {
      const result = await HttpUtil.get<{ active: boolean }>(API + '/token', undefined, {
        silent: true,
      });
      if (!result.success || !result.obj) {
        throw new Error(result.msg || 'Could not read sales token status');
      }
      return result.obj.active;
    },
  });
  const catalog = useQuery({
    queryKey: ['delegated-sales-plans'],
    queryFn: async () => {
      const result = await HttpUtil.get<{ plans: Plan[] }>(API, undefined, { silent: true });
      if (!result.success || !result.obj) {
        throw new Error(result.msg || 'Could not load sales plans');
      }
      return result.obj.plans;
    },
  });

  function open(plan: Plan | null) {
    form.resetFields();
    form.setFieldsValue(plan ?? { name: '', quotaGiB: 150, enabled: true });
    setError('');
    setEditing(plan);
  }

  async function save(values: PlanValues) {
    setSaving(true);
    setError('');
    try {
      const result = await HttpUtil.post(
        API + '/plans',
        { ...values, id: editing?.id, enabled: values.enabled ? 1 : 0 },
        { silent: true },
      );
      if (!result.success) {
        setError(result.msg || 'Could not save sales plan');
        return;
      }
      setEditing(undefined);
      await catalog.refetch();
    } finally {
      setSaving(false);
    }
  }

  function openTokenDialog(action: 'generate' | 'revoke') {
    setTokenError('');
    setSalesToken('');
    setTokenDialog(action);
  }

  async function changeToken() {
    setChangingToken(true);
    setTokenError('');
    try {
      const result = await HttpUtil.post<{ active: boolean; token: string }>(
        API + '/token',
        { action: tokenDialog },
        { silent: true },
      );
      if (!result.success || !result.obj) {
        setTokenError(result.msg || 'Could not change the sales token');
        return;
      }
      setSalesToken(result.obj.token);
      if (!result.obj.active) setTokenDialog(undefined);
      await tokenStatus.refetch();
    } catch {
      setTokenError('Could not confirm the change. Refresh the token status before retrying.');
    } finally {
      setChangingToken(false);
    }
  }

  function closeTokenDialog() {
    setSalesToken('');
    setTokenDialog(undefined);
  }

  return (
    <Card title="Sales plans" extra={<Button onClick={() => open(null)}>Add plan</Button>}>
      <Card size="small" title="توکن فروش بات">
        <Space wrap>
          <Button disabled={tokenStatus.isPending} onClick={() => openTokenDialog('generate')}>
            {tokenStatus.data ? 'جایگزینی توکن فروش' : 'ساخت توکن فروش'}
          </Button>
          <Button danger disabled={!tokenStatus.data} onClick={() => openTokenDialog('revoke')}>
            لغو توکن
          </Button>
        </Space>
        {tokenStatus.isError && <p role="alert">{tokenStatus.error.message}</p>}
      </Card>
      <Modal
        open={tokenDialog !== undefined}
        title="توکن فروش بات"
        confirmLoading={changingToken}
        closable={!changingToken}
        maskClosable={!changingToken}
        keyboard={!changingToken}
        onCancel={changingToken ? undefined : closeTokenDialog}
        cancelButtonProps={{ disabled: changingToken }}
        cancelText="انصراف"
        okText={salesToken ? 'بستن' : 'تأیید'}
        onOk={salesToken ? closeTokenDialog : changeToken}
      >
        {tokenError && <p role="alert">{tokenError}</p>}
        {salesToken ? (
          <>
            <p>توکن فقط همین بار نمایش داده می‌شود. آن را در SANAEI_SALES_TOKEN بات بگذارید.</p>
            <Input aria-label="توکن فروش جدید" value={salesToken} readOnly />
          </>
        ) : (
          <p>
            {tokenDialog === 'revoke'
              ? 'با لغو توکن، بات دسترسی به API فروش را از دست می‌دهد.'
              : 'توکن جدید بلافاصله فعال می‌شود و توکن قبلی اعتبارش را از دست می‌دهد.'}
          </p>
        )}
      </Modal>
      {catalog.isError && <p role="alert">{catalog.error.message}</p>}
      <Table<Plan>
        rowKey="id"
        loading={catalog.isPending}
        dataSource={catalog.data}
        columns={[
          { title: 'Plan', dataIndex: 'name' },
          { title: 'Quota (GiB)', dataIndex: 'quotaGiB' },
          {
            title: 'Status',
            key: 'enabled',
            render: (_, plan) => <Tag>{plan.enabled ? 'For sale' : 'Disabled'}</Tag>,
          },
          {
            title: 'Actions',
            key: 'actions',
            render: (_, plan) => <Button onClick={() => open(plan)}>Edit plan</Button>,
          },
        ]}
      />
      <Modal
        open={editing !== undefined}
        forceRender
        title={editing ? 'Edit sales plan' : 'Add sales plan'}
        okText="Save"
        confirmLoading={saving}
        onOk={() => form.submit()}
        onCancel={() => setEditing(undefined)}
      >
        {error && <p role="alert">{error}</p>}
        <Form form={form} layout="vertical" onFinish={save}>
          <Form.Item name="name" label="Plan name" rules={[{ required: true }]}>
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item name="quotaGiB" label="Quota (GiB)" rules={[{ required: true }]}>
            <InputNumber min={100} max={1000000} precision={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="enabled" label="Available for sale" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
