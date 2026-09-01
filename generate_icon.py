"""Generate a simple AI Security icon"""
from PIL import Image, ImageDraw, ImageFont

# Create 256x256 icon
size = 256
img = Image.new('RGBA', (size, size), (30, 30, 40, 255))
draw = ImageDraw.Draw(img)

# Shield shape
shield_points = [
    (128, 20),   # top
    (236, 60),   # top right
    (236, 130),  # right
    (128, 236),  # bottom
    (20, 130),   # left
    (20, 60),    # top left
]
draw.polygon(shield_points, fill=(31, 83, 141, 255), outline=(100, 160, 220, 255), width=4)

# Inner shield
draw.polygon([
    (128, 40),
    (216, 72),
    (216, 126),
    (128, 212),
    (40, 126),
    (40, 72),
], fill=(20, 60, 100, 255))

# Lock icon in center
lock_x, lock_y = 128, 118
# Lock body
body_w, body_h = 70, 50
body_x = lock_x - body_w//2
body_y = lock_y + 5
draw.rounded_rectangle(
    [body_x, body_y, body_x + body_w, body_y + body_h],
    radius=8, fill=(255, 200, 50, 255), outline=(255, 160, 0, 255), width=3
)

# Lock shackle
shackle_rect = [lock_x - 20, lock_y - 25, lock_x + 20, lock_y + 10]
draw.arc(shackle_rect, start=0, end=180, fill=(255, 200, 50, 255), width=8)

# Keyhole
draw.ellipse([lock_x - 6, lock_y + 15, lock_x + 6, lock_y + 30], fill=(30, 30, 40, 255))
draw.polygon([
    (lock_x, lock_y + 28),
    (lock_x - 5, lock_y + 42),
    (lock_x + 5, lock_y + 42),
], fill=(30, 30, 40, 255))

# Save as ICO
ico_path = "C:\\Users\\albuz\\.kimi_openclaw\\workspace\\ai-security-lab\\icon.ico"
img.save(ico_path, format='ICO', sizes=[(256,256), (128,128), (64,64), (32,32), (16,16)])

# Also save PNG preview
png_path = "C:\\Users\\albuz\\.kimi_openclaw\\workspace\\ai-security-lab\\icon_preview.png"
img.save(png_path, format='PNG')

print(f"Icon saved: {ico_path}")
print(f"Preview: {png_path}")
