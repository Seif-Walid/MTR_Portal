import { Empty, Space, Tag, Typography } from 'antd';

import type { AllocationPurpose, InventoryItem } from '../api/types';
import { PURPOSE_META } from './tags';

const ORDER: AllocationPurpose[] = ['training', 'competition', 'research', 'borrowed', 'other'];

/** The per-purpose split of everything currently in use — shown both in the
 *  hover popover on the table and inside the detail drawer. */
export default function UsageBreakdown({
  item,
  unit,
}: {
  item: InventoryItem;
  unit?: boolean;
}) {
  const entries = ORDER.filter((p) => (item.by_purpose[p] ?? 0) > 0);
  if (entries.length === 0) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Nothing in use" />;
  }
  return (
    <Space direction="vertical" size={4} style={{ minWidth: 180 }}>
      {entries.map((p) => (
        <div key={p} style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
          <Tag color={PURPOSE_META[p].color}>{PURPOSE_META[p].label}</Tag>
          <Typography.Text strong>
            {item.by_purpose[p]}
            {unit ? ` ${item.unit}` : ''}
          </Typography.Text>
        </div>
      ))}
    </Space>
  );
}
