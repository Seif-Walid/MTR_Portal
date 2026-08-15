import type { ThemeConfig } from 'antd';

// CIRCUIT — Ant Design v5 dark theme. Wrap <App/> in:
//   <ConfigProvider theme={circuitTheme}> ... </ConfigProvider>
// Pair with circuit.css (fonts, body bg, table row hover, custom bits).
export const circuitTheme: ThemeConfig = {
  token: {
    colorPrimary: '#5cc6ff',
    colorInfo: '#5cc6ff',
    colorSuccess: '#4fd6c4',
    colorWarning: '#ffb26b',
    colorError: '#ff5a6e',

    // Dark-tinted status backgrounds. Without these, AntD keeps its light-mode
    // pastel fills (e.g. error #fff2f0) while text inherits the near-white
    // colorText above — making Alert/message/Tag copy invisible. See BulkDataPage.
    colorErrorBg: 'rgba(255,90,110,.12)',
    colorErrorBorder: 'rgba(255,90,110,.35)',
    colorSuccessBg: 'rgba(79,214,196,.12)',
    colorSuccessBorder: 'rgba(79,214,196,.35)',
    colorWarningBg: 'rgba(255,178,107,.12)',
    colorWarningBorder: 'rgba(255,178,107,.35)',
    colorInfoBg: 'rgba(92,198,255,.12)',
    colorInfoBorder: 'rgba(92,198,255,.35)',

    colorBgBase: '#06080c',
    colorBgLayout: '#06080c',
    colorBgContainer: 'rgba(15,20,29,.55)',
    colorBgElevated: '#0f141d',
    colorBorder: 'rgba(120,170,230,.12)',
    colorBorderSecondary: 'rgba(120,170,230,.07)',

    colorText: '#eaf2ff',
    colorTextSecondary: 'rgba(224,236,252,.72)',
    colorTextTertiary: 'rgba(224,236,252,.55)',
    colorTextQuaternary: 'rgba(224,236,252,.4)',

    fontFamily: "'Geist Variable', 'Geist', system-ui, sans-serif",
    borderRadius: 8,
    borderRadiusLG: 12,
    wireframe: false,
  },
  components: {
    Table: {
      headerBg: 'rgba(8,11,17,.4)',
      headerColor: 'rgba(224,236,252,.4)',
      rowHoverBg: 'rgba(255,255,255,.02)',
      borderColor: 'rgba(120,170,230,.07)',
      cellPaddingBlock: 14,
    },
    Card: { colorBgContainer: 'rgba(15,20,29,.55)' },
    Segmented: {
      trackBg: 'rgba(8,11,17,.6)',
      itemSelectedBg: 'rgba(92,198,255,.16)',
      itemSelectedColor: '#eaf2ff',
      itemColor: 'rgba(224,236,252,.5)',
    },
    Button: { primaryShadow: '0 0 20px rgba(92,198,255,.35)' },
    Tabs: { inkBarColor: '#5cc6ff', itemActiveColor: '#5cc6ff', itemSelectedColor: '#eaf2ff' },
    Modal: { contentBg: '#0f141d', headerBg: '#0f141d' },
    Input: { colorBgContainer: 'rgba(8,11,17,.7)' },
    Select: { colorBgContainer: 'rgba(8,11,17,.7)', optionSelectedBg: 'rgba(92,198,255,.12)' },
  },
};
