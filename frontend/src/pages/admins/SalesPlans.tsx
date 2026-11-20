import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button, Card, Form, Input, InputNumber, Modal, Switch, Table, Tag } from 'antd';
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
  const catalog = useQuery({
    queryKey: ['delegated-sales-plans'],
    queryFn: async () => {
      const result = await HttpUtil.get<{ plans: Plan[] }>(API, undefined, { silent: true });
      if (!result.success || !result.obj) throw new Error(result.msg || 'Could not load sales plans');
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

  return (
    <Card title="Sales plans" extra={<Button onClick={() => open(null)}>Add plan</Button>}>
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
