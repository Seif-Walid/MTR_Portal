import { TreeSelect } from 'antd';
import { useEffect, useState } from 'react';

import { api } from '../api/client';
import type { PositionNode } from '../api/types';

function toTreeData(nodes: PositionNode[]): NonNullable<React.ComponentProps<typeof TreeSelect>['treeData']> {
  return nodes.map((n) => ({
    value: n.id,
    title: n.occupants.length > 0
      ? `${n.title} (${n.occupants.map((u) => u.full_name).join(', ')})`
      : `${n.title} (vacant)`,
    children: toTreeData(n.children),
  }));
}

export default function PositionPicker({ value, onChange, placeholder }: {
  value?: number;
  onChange?: (id: number | undefined) => void;
  placeholder?: string;
}) {
  const [roots, setRoots] = useState<PositionNode[]>([]);

  useEffect(() => {
    api.get<PositionNode[]>('/api/org/tree').then(setRoots).catch(() => {});
  }, []);

  return (
    <TreeSelect
      value={value}
      onChange={onChange}
      treeData={toTreeData(roots)}
      placeholder={placeholder ?? 'Pick a position in the org chart'}
      treeDefaultExpandAll
      showSearch
      treeNodeFilterProp="title"
      style={{ width: '100%' }}
    />
  );
}
