# Multi-Architecture Support

This project is configured to work seamlessly on both ARM64 and x86_64 architectures without any configuration changes.

## Supported Architectures

✅ **ARM64** (Apple Silicon: M1, M2, M3, M4)
✅ **AMD64/x86_64** (Intel/AMD processors)

## How It Works

Docker automatically detects your host architecture and builds appropriate images. No manual platform selection needed!

### Base Images Used

All base images support multi-architecture:

| Service | Image | ARM64 | AMD64 |
|---------|-------|-------|-------|
| Python API | `python:3.11-slim` | ✅ | ✅ |
| PostgreSQL | `postgres:16-alpine` | ✅ | ✅ |
| Redis | `redis:7-alpine` | ✅ | ✅ |
| Node Frontend | `node:20-alpine` | ✅ | ✅ |

### Architecture Detection

When you run the startup scripts, they automatically detect your architecture:

```bash
./start-dev.sh
# Output: 🔍 Detected architecture: arm64
# or
# Output: 🔍 Detected architecture: x86_64
```

## Switching Between Architectures

You can use the same codebase on different machines without any changes:

### Scenario 1: Development on Apple Silicon, Deploy on x86_64
```bash
# On Mac (ARM64)
git clone <repo>
./start-dev.sh  # Builds ARM64 images

# Push to Git
git push

# On Linux/Intel server (x86_64)
git pull
./start-dev.sh  # Builds x86_64 images automatically
```

### Scenario 2: Team with Mixed Hardware
- Developer A: MacBook Pro M2 (ARM64) ✅
- Developer B: MacBook Pro Intel (x86_64) ✅
- Developer C: Linux workstation (x86_64) ✅
- CI/CD Server: x86_64 ✅

All use the same Docker configuration!

## Building Multi-Platform Images (Optional)

If you need to build images that work on BOTH architectures simultaneously (for distribution):

```bash
# Enable Docker buildx
docker buildx create --use

# Build multi-platform image
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-registry/workshoppro:latest \
  --push \
  .
```

## Performance Considerations

### ARM64 (Apple Silicon)
- Native performance on M-series Macs
- No emulation overhead
- Faster builds and runtime

### x86_64 (Intel/AMD)
- Native performance on Intel/AMD processors
- Wider ecosystem support
- More pre-built packages available

### Rosetta 2 (Not Used)
We don't rely on Rosetta 2 emulation. All images are built natively for your architecture.

## Verification

Check what architecture your containers are running:

```bash
# Check architecture of running container
docker-compose -f docker-compose.yml -f docker-compose.dev.yml exec app uname -m

# Expected output:
# - On Apple Silicon: aarch64 (ARM64)
# - On Intel/AMD: x86_64
```

## Dependencies Compatibility

All Python and Node dependencies are compatible with both architectures:

### Python Packages
- FastAPI, SQLAlchemy, Celery: Pure Python (architecture-agnostic)
- asyncpg, cryptography: Provide wheels for both ARM64 and x86_64
- WeasyPrint: System dependencies installed via apt (works on both)

### Node Packages
- React, Vite, Tailwind: JavaScript (architecture-agnostic)
- Native modules: npm automatically installs correct binaries

## CI/CD Considerations

### GitHub Actions
```yaml
strategy:
  matrix:
    platform: [ubuntu-latest, macos-latest]
```

### GitLab CI
```yaml
test:
  parallel:
    matrix:
      - PLATFORM: [linux/amd64, linux/arm64]
```

## Troubleshooting

### Issue: "exec format error"
This means you're trying to run an image built for a different architecture.

**Solution**: Rebuild images on your current machine:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --no-cache
```

### Issue: Slow performance on Apple Silicon
Make sure you're NOT forcing x86_64 emulation.

**Check**: Remove any `platform: linux/amd64` directives from docker-compose files.

### Issue: Different behavior on different architectures
This is rare but can happen with:
- Floating-point precision differences
- Endianness (not an issue for ARM64/x86_64)
- Architecture-specific bugs in dependencies

**Solution**: Test on both architectures before deploying.

## Best Practices

1. ✅ **Don't hardcode platforms** - Let Docker auto-detect
2. ✅ **Use multi-arch base images** - Alpine, Debian, Ubuntu all support both
3. ✅ **Test on target architecture** - If deploying to x86_64, test there
4. ✅ **Use official images** - They're maintained for multiple architectures
5. ❌ **Avoid platform-specific code** - Keep Python/JS code portable

## Summary

Your Docker setup is fully portable between ARM64 and x86_64. No configuration changes needed when switching machines or deploying to different architectures. Just run `./start-dev.sh` and Docker handles the rest!
