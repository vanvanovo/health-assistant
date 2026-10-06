import { reactive } from 'vue'

const TOKEN_KEY = 'health-token'
const USER_KEY = 'health-user'

export const auth = reactive({
  token: localStorage.getItem(TOKEN_KEY) || '',
  username: localStorage.getItem(USER_KEY) || '',

  get isLoggedIn(): boolean {
    return !!this.token
  },

  setLogin(token: string, username: string) {
    this.token = token
    this.username = username
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, username)
  },

  logout() {
    this.token = ''
    this.username = ''
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
})
