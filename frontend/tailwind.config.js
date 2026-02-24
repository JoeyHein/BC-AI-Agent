/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./customer.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        odc: {
          50:  '#f0f4f8',
          100: '#d9e4ef',
          200: '#b3c8de',
          300: '#8dabc9',
          400: '#668fb4',
          500: '#40739e',
          600: '#2f5782',
          700: '#1e3a5f',
          800: '#142d4c',
          900: '#0C2340',
          950: '#071629',
        },
      },
      fontFamily: {
        sans: ['"Open Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
