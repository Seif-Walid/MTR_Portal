import { theme as antdThemeApi, type ThemeConfig } from 'antd';

import { FONT_SANS, ROLES, type Mode } from './tokens';

// Ant Design config for one brightness, built from the same role values the
// CSS custom properties use (tokens.ts). antd derives hover/active shades from
// concrete colours, so it gets the resolved hex rather than var() references.
export function antdTheme(mode: Mode): ThemeConfig {
  const r = ROLES[mode];
  return {
    algorithm: mode === 'dark' ? antdThemeApi.darkAlgorithm : antdThemeApi.defaultAlgorithm,
    cssVar: true,
    token: {
      colorPrimary: r.primary,
      colorInfo: r.info,
      colorSuccess: r.success,
      colorWarning: r.warning,
      colorError: r.error,
      colorLink: r['brand-fg'],

      colorErrorBg: r['error-surface'],
      colorSuccessBg: r['success-surface'],
      colorWarningBg: r['warning-surface'],
      colorInfoBg: r['info-surface'],

      colorBgBase: r.background,
      colorBgLayout: r.background,
      colorBgContainer: r.surface,
      colorBgElevated: r['surface-raised'],
      colorBorder: r.border,
      colorBorderSecondary: r['border-light'],
      colorFillQuaternary: r['surface-alt'],

      colorText: r['text-primary'],
      colorTextSecondary: r['text-secondary'],
      colorTextTertiary: r['text-tertiary'],
      colorTextQuaternary: r['text-tertiary'],
      colorTextPlaceholder: r['text-tertiary'],
      colorTextDisabled: r['text-disabled'],
      colorTextLightSolid: r['on-primary'],

      controlItemBgHover: r['surface-alt'],
      controlItemBgActive: r['primary-surface'],
      controlItemBgActiveHover: r['primary-surface'],
      controlOutline: 'transparent',

      fontFamily: FONT_SANS,
      fontSize: 14,
      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 4,
      controlHeight: 36,
      motionDurationFast: '0.1s',
      motionDurationMid: '0.15s',
      motionDurationSlow: '0.25s',
      motionEaseOut: 'cubic-bezier(0.33, 1, 0.68, 1)',
      boxShadow: `0 8px 24px ${r['shadow-color']}, 0 2px 6px ${r['shadow-color']}`,
      boxShadowSecondary: `0 8px 24px ${r['shadow-color']}, 0 2px 6px ${r['shadow-color']}`,
      boxShadowTertiary: `0 1px 2px ${r['shadow-color']}`,
      wireframe: false,
    },
    components: {
      Table: {
        headerBg: r['surface-alt'],
        headerColor: r['text-secondary'],
        rowHoverBg: r['surface-alt'],
        rowSelectedBg: r['primary-surface'],
        rowSelectedHoverBg: r['primary-surface'],
        borderColor: r['border-light'],
        cellPaddingBlock: 12,
        cellPaddingInline: 14,
      },
      Segmented: {
        trackBg: r['surface-alt'],
        itemSelectedBg: r.surface,
        itemSelectedColor: r['text-primary'],
        itemColor: r['text-secondary'],
      },
      Button: { primaryShadow: 'none', defaultShadow: 'none', dangerShadow: 'none', fontWeight: 500 },
      Tabs: { inkBarColor: r['brand-fg'], itemActiveColor: r['text-primary'], itemSelectedColor: r['text-primary'], itemHoverColor: r['text-primary'] },
      Modal: { contentBg: r['surface-raised'], headerBg: r['surface-raised'], footerBg: r['surface-raised'] },
      Drawer: { colorBgElevated: r['surface-raised'] },
      Select: { optionSelectedBg: r['primary-surface'], optionActiveBg: r['surface-alt'], optionSelectedColor: r['text-primary'] },
      Menu: { itemSelectedBg: r['primary-surface'], itemSelectedColor: r['text-primary'] },
      Tag: { defaultBg: r['surface-alt'], defaultColor: r['text-secondary'] },
      Badge: { colorError: r.signal },
    },
  };
}
