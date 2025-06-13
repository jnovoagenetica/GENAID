/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    fontFamily: {
      body: ['M PLUS Rounded 1c'],
    },
    extend: {
      transitionProperty: {
        width: 'width',
        height: 'height',
      },
      animation: {
        fastPulse: 'pulse 0.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      colors: {
        'aws-squid-ink': '#232F3E',
        'aws-sea-blue': '#005276',
        'aws-sea-blue-hover': '#003550',
        'aws-aqua': '#007faa',
        'aws-lab': '#38ef7d',
        'aws-mist': '#9ffcea',
        'aws-font-color': '#232F3E',
        'aws-font-color-white': '#ffffff',
        'aws-paper': '#f1f3f3',
        red: '#dc2626',
        'light-red': '#fee2e2',
        yellow: '#f59e0b',
        'light-yellow': '#fef9c3',
        'dark-gray': '#6b7280',
        gray: '#9ca3af',
        'light-gray': '#e5e7eb',
        //Agregamos el color soft-cyan directamente al talwind este es el color de fondo de login
        'soft-cyan': '#D4EEF3',
        //Agregamos el color login-bg para el color de el formulario de login
        'login-bg': '#E6EFE0',
        'menu-header': '#60B0C0',
        'boton-header': '#A3D1E4',
        'linea-menu': '#353030',
        'chat-user-color': '#C1D8E4',
        'dark-black': '#000000',
        'menu-divider': '#353030'

      },
    },
  },
  // eslint-disable-next-line no-undef
  plugins: [require('@tailwindcss/typography'), require('tailwind-scrollbar')],
};