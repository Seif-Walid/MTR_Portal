/* The three ways money moves, each a short form. Whoever is signed in is the
   holder — there is no "received by" / "paid by" field to fill: the server
   records the account that logged it. Dates default to today; the season is
   worked out from the date. */
import { DatePicker, Form, Input, InputNumber, Modal, Segmented, Select, Typography, message } from 'antd';
import dayjs, { type Dayjs } from 'dayjs';
import { useEffect, useMemo, useState } from 'react';

import { api, ApiError } from '../../api/client';
import type { FinanceFormOptions, MyCash } from '../../api/types';
import { egp } from '../charts';

const iso = (d?: Dayjs | null) => (d ? d.format('YYYY-MM-DD') : undefined);

function useSubmit(onDone: () => void) {
  const [busy, setBusy] = useState(false);
  const run = async (url: string, body: unknown, ok: string) => {
    setBusy(true);
    try {
      await api.post(url, body);
      message.success(ok);
      onDone();
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : 'Could not save it');
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
}

/** Methods as one tap: Cash · Instapay · Bank … */
function MethodPicker({ value, onChange, options }: {
  value?: number; onChange?: (v: number) => void; options: { id: number; name: string }[];
}) {
  if (!options.length) return <Typography.Text type="secondary">No payment methods set up yet (Finance › Advanced › Lists).</Typography.Text>;
  return (
    <Segmented
      block
      value={value}
      onChange={(v) => onChange?.(Number(v))}
      options={options.map((m) => ({ value: m.id, label: m.name }))}
    />
  );
}

/** A contact picker that also creates one: type a new name and pick "Add …". */
function ContactPicker({ value, onChange, contacts, placeholder }: {
  value?: string; onChange?: (v: string | undefined) => void;
  contacts: { id: number; name: string }[]; placeholder: string;
}) {
  const [search, setSearch] = useState('');
  const options = useMemo(() => {
    const base = contacts.map((c) => ({ value: `id:${c.id}`, label: c.name }));
    const t = search.trim();
    if (t && !contacts.some((c) => c.name.toLowerCase() === t.toLowerCase())) {
      base.push({ value: `new:${t}`, label: `Add “${t}”` });
    }
    return base;
  }, [contacts, search]);
  return (
    <Select
      showSearch
      allowClear
      value={value}
      onChange={onChange}
      onSearch={setSearch}
      filterOption={(input, o) => String(o?.label ?? '').toLowerCase().includes(input.toLowerCase()) || String(o?.value).startsWith('new:')}
      options={options}
      placeholder={placeholder}
    />
  );
}

const contactFields = (v?: string, idKey = 'party_id', nameKey = 'party_name') =>
  !v ? {} : v.startsWith('id:') ? { [idKey]: Number(v.slice(3)) } : { [nameKey]: v.slice(4) };

// --- money in ----------------------------------------------------------------
interface InValues {
  member_id?: number;
  funding_id?: number;
  contact?: string;
  source?: string;
  type_id?: number;
  amount?: number;
  method_id?: number;
  on?: Dayjs;
  note?: string;
}

export function MoneyInModal({ open, opts, onClose, onDone }: {
  open: boolean; opts: FinanceFormOptions | null; onClose: () => void; onDone: () => void;
}) {
  const [form] = Form.useForm<InValues>();
  const [kind, setKind] = useState<'dues' | 'other'>('dues');
  const { busy, run } = useSubmit(onDone);
  const memberId = Form.useWatch('member_id', form);
  const fundingId = Form.useWatch('funding_id', form);

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ on: dayjs(), method_id: opts?.methods[0]?.id });
    }
  }, [open, opts, form]);

  const owing = opts?.owing ?? [];
  const member = owing.find((o) => o.member_id === memberId);
  useEffect(() => {
    if (member && !form.getFieldValue('amount')) form.setFieldValue('amount', member.monthly_fee || undefined);
  }, [member, form]);
  const expected = opts?.expected_funding.find((f) => f.id === fundingId);
  useEffect(() => {
    if (expected) form.setFieldValue('amount', expected.amount);
  }, [expected, form]);

  const submit = (v: InValues) => {
    if (kind === 'dues') {
      void run('/api/finance/money-in/dues', {
        member_id: v.member_id, amount: v.amount, method_id: v.method_id, paid_on: iso(v.on), note: v.note,
      }, `${egp(v.amount ?? 0)} EGP from ${member?.name ?? 'member'} logged — it's with you now.`);
    } else {
      void run('/api/finance/money-in/funding', {
        amount: v.amount, method_id: v.method_id, received_on: iso(v.on), funding_id: v.funding_id,
        source: v.source, type_id: v.type_id, note: v.note, ...contactFields(v.contact),
      }, `${egp(v.amount ?? 0)} EGP received — it's with you now.`);
    }
  };

  return (
    <Modal
      open={open}
      title="Money in"
      okText="Log it"
      onOk={() => form.submit()}
      okButtonProps={{ loading: busy }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: -4 }}>
        You're logging money you took. It's recorded as with you until you hand it over.
      </Typography.Paragraph>
      <Segmented
        block
        value={kind}
        onChange={(v) => setKind(v as typeof kind)}
        options={[{ value: 'dues', label: 'Member dues' }, { value: 'other', label: 'Sponsor / other' }]}
        style={{ marginBottom: 16 }}
      />
      <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
        {kind === 'dues' ? (
          <Form.Item name="member_id" label="From" rules={[{ required: true, message: 'Who paid?' }]}
            extra={member ? `${member.tier ?? 'No tier'} · ${egp(member.monthly_fee)} EGP / month · still owes ${egp(member.balance)} EGP` : 'Everyone who owes dues this season, from the event teams.'}>
            <Select
              showSearch
              optionFilterProp="label"
              placeholder="Member"
              options={owing.map((o) => ({
                value: o.member_id,
                label: `${o.name}${o.mtr_id ? ` · ${o.mtr_id}` : ''}${o.balance > 0 ? ` · owes ${egp(o.balance)}` : ''}`,
              }))}
            />
          </Form.Item>
        ) : (
          <>
            {!!opts?.expected_funding.length && (
              <Form.Item name="funding_id" label="Settles an expected line" extra="Pick one if this is money the plan was waiting for.">
                <Select allowClear placeholder="None — new money"
                  options={opts.expected_funding.map((f) => ({ value: f.id, label: `${f.source} · ${egp(f.amount)} EGP` }))} />
              </Form.Item>
            )}
            {!fundingId && (
              <>
                <Form.Item name="contact" label="From" rules={[{ required: true, message: 'Who is it from?' }]}>
                  <ContactPicker contacts={opts?.contacts ?? []} placeholder="Sponsor, organizer… or type a new name" />
                </Form.Item>
                {!!opts?.funding_types.length && (
                  <Form.Item name="type_id" label="Type">
                    <Segmented options={opts.funding_types.map((t) => ({ value: t.id, label: t.name }))} />
                  </Form.Item>
                )}
              </>
            )}
          </>
        )}
        <Form.Item name="amount" label="Amount" rules={[{ required: true, message: 'How much?' }]}>
          <InputNumber style={{ width: '100%' }} addonAfter="EGP" min={kind === 'dues' ? undefined : 0} />
        </Form.Item>
        <Form.Item name="method_id" label="How" rules={[{ required: true, message: 'Pick a method' }]}>
          <MethodPicker options={opts?.methods ?? []} />
        </Form.Item>
        <Form.Item name="on" label="Date">
          <DatePicker style={{ width: '100%' }} allowClear={false} />
        </Form.Item>
        <Form.Item name="note" label="Note">
          <Input placeholder="Optional" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// --- money out -----------------------------------------------------------------
interface OutValues {
  item: string;
  count?: number;
  unit_cost?: number;
  method_id?: number;
  on?: Dayjs;
  event_id?: number;
  event_team_id?: number;
  category_id?: number;
  subcategory_id?: number;
  payee?: string;
  receipt?: string;
  note?: string;
}

export function MoneyOutModal({ open, opts, onClose, onDone }: {
  open: boolean; opts: FinanceFormOptions | null; onClose: () => void; onDone: () => void;
}) {
  const [form] = Form.useForm<OutValues>();
  const { busy, run } = useSubmit(onDone);
  const eventId = Form.useWatch('event_id', form);
  const count = Form.useWatch('count', form) ?? 1;
  const unit = Form.useWatch('unit_cost', form) ?? 0;

  useEffect(() => {
    if (open) {
      form.resetFields();
      form.setFieldsValue({ on: dayjs(), count: 1, method_id: opts?.methods[0]?.id });
    }
  }, [open, opts, form]);

  const teams = opts?.events.find((e) => e.id === eventId)?.teams ?? [];
  const submit = (v: OutValues) =>
    void run('/api/finance/money-out', {
      item: v.item, count: v.count, unit_cost: v.unit_cost, method_id: v.method_id, spent_on: iso(v.on),
      event_id: v.event_id, event_team_id: v.event_team_id, category_id: v.category_id,
      subcategory_id: v.subcategory_id, receipt: v.receipt, note: v.note,
      ...contactFields(v.payee, 'payee_party_id', 'payee_name'),
    }, `${egp(count * unit)} EGP spent on ${v.item} — logged as paid by you.`);

  return (
    <Modal
      open={open}
      title="Money out"
      okText="Log it"
      onOk={() => form.submit()}
      okButtonProps={{ loading: busy }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: -4 }}>
        You're logging money you paid out of what you hold.
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
        <Form.Item name="item" label="What for" rules={[{ required: true, message: 'What was bought?' }]}>
          <Input placeholder="e.g. Thrusters, transport, registration fee" />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
          <Form.Item name="count" label="Count">
            <InputNumber style={{ width: '100%' }} min={0.001} />
          </Form.Item>
          <Form.Item name="unit_cost" label={count > 1 ? 'Each' : 'Cost'} rules={[{ required: true, message: 'How much?' }]}
            extra={count > 1 && unit ? `Total ${egp(count * unit)} EGP` : undefined}>
            <InputNumber style={{ width: '100%' }} addonAfter="EGP" min={0} />
          </Form.Item>
        </div>
        <Form.Item name="method_id" label="How" rules={[{ required: true, message: 'Pick a method' }]}>
          <MethodPicker options={opts?.methods ?? []} />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item name="event_id" label="For event">
            <Select allowClear placeholder="Team-wide" showSearch optionFilterProp="label"
              onChange={() => form.setFieldValue('event_team_id', undefined)}
              options={(opts?.events ?? []).map((e) => ({ value: e.id, label: e.name }))} />
          </Form.Item>
          <Form.Item name="event_team_id" label="Team">
            <Select allowClear disabled={!teams.length} placeholder={eventId ? 'Whole event' : 'Pick an event first'}
              options={teams.map((t) => ({ value: t.id, label: t.name }))} />
          </Form.Item>
          <Form.Item name="category_id" label="Category">
            <Select allowClear placeholder="—" options={(opts?.categories ?? []).map((c) => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="subcategory_id" label="Sub-category">
            <Select allowClear placeholder="—" options={(opts?.subcategories ?? []).map((c) => ({ value: c.id, label: c.name }))} />
          </Form.Item>
        </div>
        <Form.Item name="payee" label="Paid to">
          <ContactPicker contacts={opts?.contacts ?? []} placeholder="Supplier (optional) — or type a new name" />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Form.Item name="on" label="Date">
            <DatePicker style={{ width: '100%' }} allowClear={false} />
          </Form.Item>
          <Form.Item name="receipt" label="Receipt link">
            <Input placeholder="Optional" />
          </Form.Item>
        </div>
        <Form.Item name="note" label="Note">
          <Input placeholder="Optional" />
        </Form.Item>
      </Form>
    </Modal>
  );
}

// --- hand-over -------------------------------------------------------------------
interface HandValues {
  to_user_id?: number;
  amount?: number;
  fees?: number;
  from_method_id?: number;
  to_method_id?: number;
  on?: Dayjs;
  note?: string;
}

export function HandoverModal({ open, opts, mine, onClose, onDone }: {
  open: boolean; opts: FinanceFormOptions | null; mine: MyCash | null; onClose: () => void; onDone: () => void;
}) {
  const [form] = Form.useForm<HandValues>();
  const { busy, run } = useSubmit(onDone);
  const fromMethod = Form.useWatch('from_method_id', form);
  const toUser = Form.useWatch('to_user_id', form);

  useEffect(() => {
    if (open) {
      form.resetFields();
      const richest = [...(mine?.methods ?? [])].filter((m) => m.id != null).sort((a, b) => b.amount - a.amount)[0];
      form.setFieldsValue({ on: dayjs(), from_method_id: richest?.id ?? opts?.methods[0]?.id ?? undefined });
    }
  }, [open, opts, mine, form]);

  const have = mine?.methods.find((m) => m.id === fromMethod)?.amount ?? 0;
  const holders = opts?.holders ?? [];
  const to = holders.find((h) => h.id === toUser);
  const submit = (v: HandValues) =>
    void run('/api/finance/handover', {
      to_user_id: v.to_user_id, amount: v.amount, fees: v.fees, from_method_id: v.from_method_id,
      to_method_id: v.to_method_id, on: iso(v.on), note: v.note,
    }, to?.me ? 'Moved between your methods.' : `Handed ${egp(v.amount ?? 0)} EGP to ${to?.name ?? 'them'}.`);

  return (
    <Modal
      open={open}
      title="Hand over cash"
      okText="Hand over"
      onOk={() => form.submit()}
      okButtonProps={{ loading: busy }}
      onCancel={onClose}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: -4 }}>
        Money leaves what you hold and becomes theirs. Pick yourself to move money between methods (e.g. deposit cash in the bank).
      </Typography.Paragraph>
      <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
        <Form.Item name="to_user_id" label="To" rules={[{ required: true, message: 'Who gets it?' }]}>
          <Select showSearch optionFilterProp="label" placeholder="A cash holder"
            options={holders.map((h) => ({ value: h.id, label: h.me ? `${h.name} (me — move between methods)` : h.name }))} />
        </Form.Item>
        <Form.Item name="from_method_id" label="From your" rules={[{ required: true, message: 'Pick a method' }]}
          extra={`You hold ${egp(have)} EGP there.`}>
          <MethodPicker options={opts?.methods ?? []} />
        </Form.Item>
        <Form.Item name="to_method_id" label="Arrives as" extra="Leave empty if it stays the same method.">
          <Select allowClear placeholder="Same method" options={(opts?.methods ?? []).map((m) => ({ value: m.id, label: m.name }))} />
        </Form.Item>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
          <Form.Item name="amount" label="Amount" rules={[{ required: true, message: 'How much?' }]}>
            <InputNumber style={{ width: '100%' }} addonAfter="EGP" min={0} />
          </Form.Item>
          <Form.Item name="fees" label="Fees">
            <InputNumber style={{ width: '100%' }} min={0} />
          </Form.Item>
        </div>
        <Form.Item name="on" label="Date">
          <DatePicker style={{ width: '100%' }} allowClear={false} />
        </Form.Item>
        <Form.Item name="note" label="Note">
          <Input placeholder="Optional" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
