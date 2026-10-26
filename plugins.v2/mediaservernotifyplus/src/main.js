import '@mdi/font/css/materialdesignicons.css'
import 'vuetify/styles'
import { createApp } from 'vue'
import { createVuetify } from 'vuetify'
import App from './App.vue'

// The standalone preview needs local registration; MoviePilot supplies Vuetify in production.
const components = import.meta.env.DEV ? await import('vuetify/components') : {}
const directives = import.meta.env.DEV ? await import('vuetify/directives') : {}

createApp(App).use(createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: 'dark',
    themes: { dark: { colors: { primary: '#9155fd', surface: '#1e1f25', background: '#17181d' } } },
  },
})).mount('#app')
