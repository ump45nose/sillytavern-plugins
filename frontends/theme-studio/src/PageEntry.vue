<script setup>
import Page from './Page.vue'
defineProps({api:Object,pluginId:{type:String,default:'ThemeStudio'}})
</script>
<template><Page :api="api" :plugin-id="pluginId" /></template>
