# Creality Hi Firmware

Steps to extract the firmware.

```
rm -rf ./*
cpio -idv < ~/Downloads/CR4NU200360C20_ota_img_V1.1.0.50.img
unsquashfs -f -d . rootfs
rm rootfs cpio_item_md5
git add .
git commit -m "Firmware vX.X.X.XX"
git push
```
```
