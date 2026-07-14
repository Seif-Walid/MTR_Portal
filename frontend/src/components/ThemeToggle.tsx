import { MoonOutlined, SunOutlined } from '@ant-design/icons';
import { Button, Tooltip } from 'antd';

import { useThemeMode } from '../theme/ThemeContext';

export default function ThemeToggle({ onDark }: { onDark?: boolean }) {
  const { mode, toggle } = useThemeMode();
  const icon = mode === 'dark' ? <SunOutlined /> : <MoonOutlined />;
  return (
    <Tooltip title={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
      <Button
        type="text"
        aria-label="Toggle dark mode"
        icon={icon}
        onClick={toggle}
        style={onDark ? { color: '#f5f2ea' } : undefined}
      />
    </Tooltip>
  );
}
