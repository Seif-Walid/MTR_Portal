import { Empty, Table, Tag, Typography } from 'antd';

import type { Allocation, AllocationPurpose, InventoryItem } from '../api/types';
import { PURPOSE_META } from './tags';

/** Column identity: a distinct competition is its own column; otherwise group
 *  by purpose + free-text label. */
function bucketKey(a: Allocation): string {
  return a.competition ? `comp:${a.competition.id}` : `${a.purpose}||${a.label}`;
}

function bucketHeader(a: Allocation): string {
  return a.display_label || PURPOSE_META[a.purpose].label;
}

const PURPOSE_ORDER: AllocationPurpose[] = [
  'training',
  'competition',
  'research',
  'borrowed',
  'other',
];

interface Bucket {
  key: string;
  header: string;
  purpose: AllocationPurpose;
}

interface Row {
  key: string;
  person: string;
  unassigned?: boolean;
  total: number;
  [bucketKey: string]: string | number | boolean | undefined;
}

/** Rows = people (plus an unassigned pool), columns = each distinct activity
 *  (R&D, Borrowed, and one per competition/project), cells = units held. Every
 *  number is derived from the item's allocations — no hardcoded data. */
export default function HoldingsMatrix({ item }: { item: InventoryItem }) {
  if (item.allocations.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Nothing allocated yet" />;
  }

  // distinct activity columns, ordered by purpose then label
  const buckets: Bucket[] = [];
  const bucketIndex = new Map<string, Bucket>();
  const sorted = [...item.allocations].sort(
    (a, b) =>
      PURPOSE_ORDER.indexOf(a.purpose) - PURPOSE_ORDER.indexOf(b.purpose) ||
      a.label.localeCompare(b.label),
  );
  for (const a of sorted) {
    const key = bucketKey(a);
    if (!bucketIndex.has(key)) {
      const bucket: Bucket = { key, header: bucketHeader(a), purpose: a.purpose };
      bucketIndex.set(key, bucket);
      buckets.push(bucket);
    }
  }

  // one row per holder (+ an unassigned pool row), summing units per bucket
  const rows = new Map<string, Row>();
  for (const a of item.allocations) {
    const rowKey = a.holder ? `u${a.holder.id}` : 'unassigned';
    const person = a.holder ? a.holder.full_name : 'Unassigned pool';
    const row =
      rows.get(rowKey) ?? ({ key: rowKey, person, unassigned: !a.holder, total: 0 } as Row);
    const bKey = bucketKey(a);
    row[bKey] = ((row[bKey] as number) ?? 0) + a.quantity;
    row.total = row.total + a.quantity;
    rows.set(rowKey, row);
  }

  // holders first (alphabetical), unassigned pool last
  const data = [...rows.values()].sort((a, b) => {
    if (a.unassigned !== b.unassigned) return a.unassigned ? 1 : -1;
    return a.person.localeCompare(b.person);
  });

  const columns = [
    {
      title: 'Person',
      dataIndex: 'person',
      fixed: 'left' as const,
      render: (v: string, r: Row) =>
        r.unassigned ? <Typography.Text type="secondary">{v}</Typography.Text> : <Typography.Text strong>{v}</Typography.Text>,
    },
    ...buckets.map((b) => ({
      title: <Tag color={PURPOSE_META[b.purpose].color} style={{ margin: 0 }}>{b.header}</Tag>,
      dataIndex: b.key,
      align: 'center' as const,
      width: 96,
      render: (v: number | undefined) =>
        v ? <Typography.Text>{v}</Typography.Text> : <Typography.Text type="secondary">—</Typography.Text>,
    })),
    {
      title: 'Total',
      dataIndex: 'total',
      align: 'center' as const,
      width: 80,
      render: (v: number) => <Typography.Text strong>{v}</Typography.Text>,
    },
  ];

  return (
    <Table<Row>
      size="small"
      bordered
      pagination={false}
      dataSource={data}
      columns={columns}
      scroll={{ x: 'max-content' }}
      summary={(pageData) => {
        const colTotal = (key: string) =>
          pageData.reduce((sum, r) => sum + ((r[key] as number) ?? 0), 0);
        return (
          <Table.Summary.Row>
            <Table.Summary.Cell index={0}>
              <Typography.Text type="secondary">In use</Typography.Text>
            </Table.Summary.Cell>
            {buckets.map((b, i) => (
              <Table.Summary.Cell index={i + 1} key={b.key} align="center">
                <Typography.Text>{colTotal(b.key)}</Typography.Text>
              </Table.Summary.Cell>
            ))}
            <Table.Summary.Cell index={buckets.length + 1} align="center">
              <Typography.Text strong>{item.in_use}</Typography.Text>
            </Table.Summary.Cell>
          </Table.Summary.Row>
        );
      }}
    />
  );
}
