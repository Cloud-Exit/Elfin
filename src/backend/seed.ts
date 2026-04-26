import { prisma } from './db.js'
import { hashPassword } from './auth.js'

function randomPassword(length = 16): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*'
  let pass = ''
  for (let i = 0; i < length; i++) {
    pass += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return pass
}

async function seed() {
  const adminExists = await prisma.user.findFirst({ where: { role: 'admin' } })
  if (adminExists) {
    console.log('Admin user already exists. Skipping seed.')
    return
  }

  const password = randomPassword()
  const hash = await hashPassword(password)

  await prisma.user.create({
    data: {
      username: 'admin',
      passwordHash: hash,
      role: 'admin',
      mustChangePassword: true,
    },
  })

  console.log('========================================')
  console.log('Admin user created:')
  console.log('  Username: admin')
  console.log('  Password:', password)
  console.log('========================================')
  console.log('Login and change password immediately.')
}

seed().catch((err) => {
  console.error('Seed failed:', err)
  process.exit(1)
})
